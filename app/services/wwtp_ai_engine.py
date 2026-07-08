"""
污水处理厂智能加药预测模块 - 核心引擎
======================================
功能：CSV数据导入 -> 数据清洗 -> 特征工程 -> 可调参数训练 -> 实时推理

嵌入到现有系统中使用，不依赖命令行参数。
"""

from __future__ import annotations

import json
import logging
import os
import warnings
from collections import deque
from typing import Any, Dict, List, Optional, Tuple, Union

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from app.services import feature_schema

# P3-19 修复：不再全局禁用所有警告，仅抑制 lightgbm 在生产环境下的告警噪声。
warnings.filterwarnings("ignore", category=UserWarning, module="lightgbm")

logger = logging.getLogger(__name__)

# ============================================================
# 常量定义
# ============================================================
# P1-6：RAW_COLS / TAG_TO_RAW_MAP 改为从 feature_schema 单一数据源派生。
RAW_COLS = feature_schema.raw_cols()

# 与现有系统 sensor_tag 的映射（用于从数据库读取数据时转换）
TAG_TO_RAW_MAP = feature_schema.tag_to_raw_map()

RAW_TO_TAG_MAP = {v: k for k, v in TAG_TO_RAW_MAP.items()}

DEFAULT_TRAIN_CONFIG = {
    "task1": {
        "num_leaves": 63,
        "max_depth": 8,
        "min_data_in_leaf": 50,
        "min_sum_hessian_in_leaf": 0.001,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "lambda_l1": 0.1,
        "lambda_l2": 1.0,
        "num_boost_round": 2000,
        "early_stopping_rounds": 100,
    },
    "task2": {
        "num_leaves": 31,
        "max_depth": 6,
        "min_data_in_leaf": 80,
        "min_sum_hessian_in_leaf": 0.01,
        "learning_rate": 0.05,
        "feature_fraction": 0.7,
        "bagging_fraction": 0.7,
        "bagging_freq": 5,
        "lambda_l1": 0.5,
        "lambda_l2": 2.0,
        "num_boost_round": 2000,
        "early_stopping_rounds": 150,
    },
    "split": {"train_ratio": 0.7, "val_ratio": 0.15},
    "seed": 42,
}


# ============================================================
# 1. CSV数据导入与清洗
# ============================================================
class DataImporter:
    """CSV数据导入器：自动检测编码、校验字段、清洗数据"""

    SUPPORTED_ENCODINGS = ["utf-8", "gbk", "gb2312", "utf-8-sig"]

    @classmethod
    def load(cls, csv_path: str) -> pd.DataFrame:
        """
        从CSV文件加载原始数据

        Args:
            csv_path: CSV文件路径

        Returns:
            清洗后的DataFrame，包含13个标准字段
        """
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV文件不存在: {csv_path}")

        # 尝试多种编码
        df = None
        for enc in cls.SUPPORTED_ENCODINGS:
            try:
                df = pd.read_csv(csv_path, encoding=enc)
                logger.info("[数据导入] 成功使用编码: %s", enc)
                break
            except UnicodeDecodeError:
                continue

        if df is None:
            raise ValueError(
                f"无法解析CSV文件编码，请确保文件为utf-8或gbk编码: {csv_path}"
            )

        # 字段映射：自动识别常见的中文/英文列名
        df = cls._map_columns(df)

        # 校验必要字段
        missing = [c for c in RAW_COLS if c not in df.columns]
        if missing:
            raise ValueError(
                f"CSV文件缺少必要字段: {missing}\n实际列名: {list(df.columns)}"
            )

        # 只保留需要的列
        df = df[RAW_COLS].copy()

        # 解析时间戳
        df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed", dayfirst=False)

        # 按时间排序
        df = df.sort_values("timestamp").reset_index(drop=True)

        logger.info(
            "[数据导入] 共 %d 条记录，时间范围: %s ~ %s",
            len(df), df["timestamp"].min(), df["timestamp"].max(),
        )

        # 数据清洗
        df = cls._clean(df)

        return df

    @classmethod
    def load_from_text(cls, csv_text: str) -> pd.DataFrame:
        """从CSV文本内容加载原始数据（用于前端直接上传）"""
        from io import StringIO

        df = None
        for enc in cls.SUPPORTED_ENCODINGS:
            try:
                df = pd.read_csv(StringIO(csv_text), encoding=enc)
                break
            except UnicodeDecodeError:
                continue

        if df is None:
            # 尝试直接读取（utf-8）
            try:
                df = pd.read_csv(StringIO(csv_text))
            except Exception as exc:
                raise ValueError("无法解析CSV文件编码") from exc

        df = cls._map_columns(df)
        missing = [c for c in RAW_COLS if c not in df.columns]
        if missing:
            raise ValueError(f"CSV文件缺少必要字段: {missing}")

        df = df[RAW_COLS].copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed", dayfirst=False)
        df = df.sort_values("timestamp").reset_index(drop=True)
        df = cls._clean(df)
        return df

    @classmethod
    def _map_columns(cls, df: pd.DataFrame) -> pd.DataFrame:
        """自动映射常见的中文列名到标准英文列名"""
        mapping = {
            # 时间
            "时间": "timestamp",
            "Time": "timestamp",
            "time": "timestamp",
            # 进水流量
            "生化池A进水流量过程值": "inflow_flow",
            "进水流量": "inflow_flow",
            # 进水总磷
            "进水总磷过程值": "inflow_tp",
            "进水TP": "inflow_tp",
            # 进水pH
            "进水在线PH过程值": "inflow_ph",
            "进水pH": "inflow_ph",
            "进水在线pH过程值": "inflow_ph",
            # 出水总磷
            "出水总磷过程值": "outflow_tp",
            "出水TP": "outflow_tp",
            # 回流
            "高密A1回流流量过程值": "high_density_a1_return",
            "高密A2回流流量过程值": "high_density_a2_return",
            # ORP
            "生化池A东ORP1过程值": "orp_east_1",
            "生化池A东ORP2过程值": "orp_east_2",
            "生化池A西ORP1过程值": "orp_west_1",
            "生化池A西ORP2过程值": "orp_west_2",
            # MLSS
            "生化池A东MLSS过程值": "mlss_east",
            "生化池A西MLSS过程值": "mlss_west",
            # PAC
            "PAC1加药流量过程值": "pac_dosage",
            "PAC加药流量": "pac_dosage",
        }

        renamed = {}
        for old_col in df.columns:
            old_col_stripped = old_col.strip()
            if old_col_stripped in mapping:
                renamed[old_col] = mapping[old_col_stripped]

        if renamed:
            df = df.rename(columns=renamed)
            logger.info("[字段映射] 自动映射 %d 个字段", len(renamed))

        return df

    @classmethod
    def _clean(cls, df: pd.DataFrame) -> pd.DataFrame:
        """数据清洗"""
        # 处理0值异常：流量、ORP、MLSS为0时视为异常，用线性插值
        zero_cols = [
            "inflow_flow",
            "orp_east_1",
            "orp_east_2",
            "orp_west_1",
            "orp_west_2",
            "mlss_east",
            "mlss_west",
        ]
        for col in zero_cols:
            df.loc[df[col] == 0, col] = np.nan
            df[col] = df[col].interpolate(method="linear", limit_direction="both")

        # 总磷0值：前向填充
        for col in ["inflow_tp", "outflow_tp"]:
            df.loc[df[col] == 0, col] = np.nan
            df[col] = df[col].ffill().bfill()

        # 确保数值类型
        for col in RAW_COLS:
            if col != "timestamp":
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 删除仍有NaN的行
        before = len(df)
        df = df.dropna().reset_index(drop=True)
        after = len(df)
        if before != after:
            logger.info("[数据清洗] 删除 %d 条含NaN记录，剩余 %d 条", before - after, after)

        return df


# ============================================================
# 2. 特征工程
# ============================================================
class FeatureEngineer:
    """特征工程：从原始数据构建模型训练/推理所需的特征"""

    @staticmethod
    def build_features(
        df: pd.DataFrame,
        for_training: bool = True,
        hrt_minutes: float | None = None,
        sample_interval_minutes: float = 5.0,
    ) -> Dict[str, Any]:
        """
        构建两个任务的数据集

        Args:
            df: 清洗后的原始数据（至少包含RAW_COLS）
            for_training: 是否为训练模式（训练模式需要构建标签）
            hrt_minutes: 出水TP水力停留时间（分钟），None表示自动推断
            sample_interval_minutes: 采样间隔（分钟）

        Returns:
            dict: {'task1': df1, 'task2': df2, 'task1_features': [...], 'task2_features': [...],
                   'label_mode': ..., 'used_lag_rows': ..., 'hrt_minutes': ..., 'sample_interval_minutes': ...}
        """
        df = df.copy()
        df = FeatureEngineer._add_time_features(df)
        
        if sample_interval_minutes <= 0 and 'timestamp' in df.columns:
            inferred_interval = FeatureEngineer._infer_sample_interval(df)
            sample_interval_minutes = inferred_interval
            logger.info("[特征工程] 自动推断采样间隔: %.1f 分钟", inferred_interval)
        
        df = FeatureEngineer._add_interaction_features(df)
        df = FeatureEngineer._add_lag_features(df)
        df = FeatureEngineer._add_rolling_features(df)
        df = FeatureEngineer._add_diff_features(df)
        df = FeatureEngineer._add_pac_effective_features(df, sample_interval_minutes)

        # 任务1特有
        df["outflow_tp_lag1_above_target"] = (df["outflow_tp_lag1"] > 0.3).astype(int)
        df["outflow_tp_lag1_deviation"] = df["outflow_tp_lag1"] - 0.3

        # 任务2特有
        df, label_mode, used_lag_rows = FeatureEngineer._add_next_outflow_tp(
            df, hrt_minutes, sample_interval_minutes
        )

        # 构建数据集
        task1_features = [
            "inflow_flow",
            "inflow_tp",
            "inflow_ph",
            "orp_east_1",
            "orp_east_2",
            "orp_west_1",
            "orp_west_2",
            "mlss_east",
            "mlss_west",
            "high_density_a1_return",
            "high_density_a2_return",
            "hour_sin",
            "hour_cos",
            "dayofweek",
            "is_weekend",
            "tp_load",
            "orp_east_avg",
            "orp_west_avg",
            "orp_total_avg",
            "orp_east_diff",
            "orp_west_diff",
            "mlss_avg",
            "mlss_diff",
            "return_total",
            "outflow_tp_lag1",
            "outflow_tp_lag2",
            "outflow_tp_lag3",
            "outflow_tp_lag6",
            "outflow_tp_lag12",
            "outflow_tp_lag1_above_target",
            "outflow_tp_lag1_deviation",
            "inflow_flow_lag1",
            "inflow_flow_lag2",
            "inflow_flow_lag3",
            "inflow_flow_lag6",
            "inflow_flow_lag12",
            "inflow_tp_lag1",
            "inflow_tp_lag2",
            "inflow_tp_lag3",
            "inflow_tp_lag6",
            "inflow_tp_lag12",
            "inflow_ph_lag1",
            "inflow_ph_lag2",
            "inflow_ph_lag3",
            "orp_total_avg_lag1",
            "orp_total_avg_lag3",
            "orp_total_avg_lag6",
            "mlss_avg_lag1",
            "mlss_avg_lag3",
            "mlss_avg_lag6",
            "tp_load_lag1",
            "tp_load_lag3",
            "tp_load_lag6",
            "pac_dosage_lag1",
            "pac_dosage_lag2",
            "pac_dosage_lag3",
            "pac_dosage_lag6",
            "inflow_flow_rollmean_3",
            "inflow_flow_rollmean_6",
            "inflow_flow_rollmean_12",
            "inflow_flow_rollstd_3",
            "inflow_flow_rollstd_6",
            "inflow_tp_rollmean_3",
            "inflow_tp_rollmean_6",
            "inflow_tp_rollmean_12",
            "inflow_tp_rollstd_3",
            "inflow_tp_rollstd_6",
            "outflow_tp_rollmean_3",
            "outflow_tp_rollmean_6",
            "outflow_tp_rollmean_12",
            "outflow_tp_rollstd_3",
            "outflow_tp_rollstd_6",
            "orp_total_avg_rollmean_3",
            "orp_total_avg_rollmean_6",
            "mlss_avg_rollmean_3",
            "mlss_avg_rollmean_6",
            "pac_dosage_rollmean_3",
            "pac_dosage_rollmean_6",
            "pac_dosage_rollmean_12",
            "pac_dosage_rollstd_3",
            "pac_dosage_rollstd_6",
            "inflow_flow_diff1",
            "inflow_flow_diff3",
            "inflow_flow_diff6",
            "inflow_tp_diff1",
            "inflow_tp_diff3",
            "inflow_tp_diff6",
            "tp_load_diff1",
            "tp_load_diff3",
            "tp_load_diff6",
            "orp_total_avg_diff1",
            "orp_total_avg_diff3",
            "pac_dosage_diff1",
            "pac_dosage_diff3",
            "pac_dosage_diff6",
        ]

        task2_features = [
            "inflow_flow",
            "inflow_tp",
            "inflow_ph",
            "orp_east_1",
            "orp_east_2",
            "orp_west_1",
            "orp_west_2",
            "mlss_east",
            "mlss_west",
            "high_density_a1_return",
            "high_density_a2_return",
            "pac_dosage",
            "outflow_tp",
            "hour_sin",
            "hour_cos",
            "dayofweek",
            "is_weekend",
            "tp_load",
            "orp_east_avg",
            "orp_west_avg",
            "orp_total_avg",
            "orp_east_diff",
            "orp_west_diff",
            "mlss_avg",
            "mlss_diff",
            "return_total",
            "inflow_flow_lag1",
            "inflow_flow_lag2",
            "inflow_flow_lag3",
            "inflow_flow_lag6",
            "inflow_tp_lag1",
            "inflow_tp_lag2",
            "inflow_tp_lag3",
            "inflow_tp_lag6",
            "inflow_ph_lag1",
            "inflow_ph_lag2",
            "outflow_tp_lag1",
            "outflow_tp_lag2",
            "outflow_tp_lag3",
            "outflow_tp_lag6",
            "outflow_tp_lag12",
            "orp_total_avg_lag1",
            "orp_total_avg_lag3",
            "mlss_avg_lag1",
            "mlss_avg_lag3",
            "tp_load_lag1",
            "tp_load_lag3",
            "pac_dosage_lag1",
            "pac_dosage_lag2",
            "pac_dosage_lag3",
            "pac_dosage_lag6",
            "pac_dosage_lag12",
            "pac_dosage_lag18",
            "pac_dosage_lag24",
            "pac_effective_tau60",
            "pac_effective_tau120",
            "pac_effective_tau180",
            "pac_effective_tau240",
            "inflow_flow_rollmean_3",
            "inflow_flow_rollmean_6",
            "inflow_flow_rollstd_3",
            "inflow_tp_rollmean_3",
            "inflow_tp_rollmean_6",
            "inflow_tp_rollstd_3",
            "outflow_tp_rollmean_3",
            "outflow_tp_rollmean_6",
            "outflow_tp_rollstd_3",
            "orp_total_avg_rollmean_3",
            "orp_total_avg_rollmean_6",
            "mlss_avg_rollmean_3",
            "mlss_avg_rollmean_6",
            "pac_dosage_rollmean_3",
            "pac_dosage_rollmean_6",
            "pac_dosage_rollstd_3",
            "inflow_flow_diff1",
            "inflow_flow_diff3",
            "inflow_tp_diff1",
            "inflow_tp_diff3",
            "tp_load_diff1",
            "tp_load_diff3",
            "pac_dosage_diff1",
            "pac_dosage_diff3",
            "orp_total_avg_diff1",
        ]

        # 数据集1：PAC加药量预测
        cols1 = ["timestamp"] + task1_features + ["pac_dosage"]
        df1 = df[cols1].dropna().reset_index(drop=True)

        # 数据集2：TP变化量预测
        cols2 = ["timestamp"] + task2_features + ["tp_delta", "next_outflow_tp"]
        df2 = df[cols2].dropna().reset_index(drop=True)

        return {
            "task1": df1,
            "task2": df2,
            "task1_features": task1_features,
            "task2_features": task2_features,
            "label_mode": label_mode,
            "used_lag_rows": used_lag_rows,
            "hrt_minutes": hrt_minutes,
            "sample_interval_minutes": sample_interval_minutes,
        }

    @staticmethod
    def _add_time_features(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["hour"] = df["timestamp"].dt.hour
        df["dayofweek"] = df["timestamp"].dt.dayofweek
        df["is_weekend"] = (df["dayofweek"] >= 5).astype(int)
        df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
        df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
        return df

    @staticmethod
    def _add_interaction_features(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["tp_load"] = df["inflow_flow"] * df["inflow_tp"]
        df["orp_east_avg"] = (df["orp_east_1"] + df["orp_east_2"]) / 2
        df["orp_west_avg"] = (df["orp_west_1"] + df["orp_west_2"]) / 2
        df["orp_total_avg"] = (df["orp_east_avg"] + df["orp_west_avg"]) / 2
        df["orp_east_diff"] = df["orp_east_1"] - df["orp_east_2"]
        df["orp_west_diff"] = df["orp_west_1"] - df["orp_west_2"]
        df["mlss_avg"] = (df["mlss_east"] + df["mlss_west"]) / 2
        df["mlss_diff"] = df["mlss_east"] - df["mlss_west"]
        df["return_total"] = df["high_density_a1_return"] + df["high_density_a2_return"]
        return df

    @staticmethod
    def _add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        lag_cols = [
            "inflow_flow",
            "inflow_tp",
            "inflow_ph",
            "outflow_tp",
            "orp_total_avg",
            "mlss_avg",
            "tp_load",
            "pac_dosage",
        ]
        for col in lag_cols:
            for lag in [1, 2, 3, 6, 12, 18, 24]:
                df[f"{col}_lag{lag}"] = df[col].shift(lag)
        return df

    @staticmethod
    def _add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        roll_cols = [
            "inflow_flow",
            "inflow_tp",
            "outflow_tp",
            "orp_total_avg",
            "mlss_avg",
            "pac_dosage",
        ]
        for col in roll_cols:
            for w in [3, 6, 12, 36, 72]:
                df[f"{col}_rollmean_{w}"] = (
                    df[col].shift(1).rolling(window=w, min_periods=1).mean()
                )
                df[f"{col}_rollstd_{w}"] = (
                    df[col].shift(1).rolling(window=w, min_periods=1).std()
                )
                df[f"{col}_rollmax_{w}"] = (
                    df[col].shift(1).rolling(window=w, min_periods=1).max()
                )
                df[f"{col}_rollmin_{w}"] = (
                    df[col].shift(1).rolling(window=w, min_periods=1).min()
                )
        return df

    @staticmethod
    def _add_diff_features(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        diff_cols = [
            "inflow_flow",
            "inflow_tp",
            "outflow_tp",
            "tp_load",
            "orp_total_avg",
            "pac_dosage",
        ]
        for col in diff_cols:
            for p in [1, 3, 6, 12]:
                df[f"{col}_diff{p}"] = df[col].diff(p)
        return df

    @staticmethod
    def _add_next_outflow_tp(
        df: pd.DataFrame,
        hrt_minutes: float | None,
        sample_interval_minutes: float = 5.0,
    ) -> tuple[pd.DataFrame, str, int]:
        """
        为任务2构建标签：下一次出水TP及变化量

        支持两种模式：
        - 模式A（固定延迟）：hrt_minutes > 0 时，用 outflow_tp.shift(-lag_rows) 构建标签
        - 模式B（自适应推断）：hrt_minutes 为 None 时，用互相关分析自动推断最佳对齐 lag

        Args:
            df: 输入数据
            hrt_minutes: 水力停留时间（分钟），None 表示自动推断
            sample_interval_minutes: 采样间隔（分钟）

        Returns:
            (df, label_mode, used_lag_rows)
        """
        df = df.copy()
        n = len(df)

        if hrt_minutes is not None and hrt_minutes > 0:
            lag_rows = max(1, int(round(hrt_minutes / sample_interval_minutes)))
            label_mode = "fixed_hrt"
        else:
            lag_rows = FeatureEngineer._auto_detect_best_lag(
                df, sample_interval_minutes
            )
            label_mode = "auto_detected"

        if lag_rows >= n:
            lag_rows = max(1, n // 4)

        df["next_outflow_tp"] = df["outflow_tp"].shift(-lag_rows)
        df["tp_delta"] = df["next_outflow_tp"] - df["outflow_tp"]

        return df, label_mode, lag_rows

    @staticmethod
    def _auto_detect_best_lag(
        df: pd.DataFrame,
        sample_interval_minutes: float = 5.0,
        min_lag_minutes: float = 30.0,
        max_lag_minutes: float = 360.0,
    ) -> int:
        """
        用互相关分析自动推断 PAC 变化量与 TP 变化量的最佳对齐 lag

        候选 lag 范围：min_lag_minutes 到 max_lag_minutes，选择负相关最强的 lag。
        优先使用 scipy，没有 scipy 时用 numpy 实现 pearson 相关。

        Returns:
            最佳 lag 的行数（整数）
        """
        min_lag = max(1, int(round(min_lag_minutes / sample_interval_minutes)))
        max_lag = min(len(df) // 3, int(round(max_lag_minutes / sample_interval_minutes)))
        if max_lag <= min_lag:
            return min_lag

        pac_diff = df["pac_dosage"].diff().fillna(0).values
        tp_diff = df["outflow_tp"].diff().fillna(0).values

        best_lag = min_lag
        best_corr = 0.0

        try:
            from scipy.signal import correlate

            pac_norm = (pac_diff - np.mean(pac_diff)) / (np.std(pac_diff) + 1e-12)
            tp_norm = (tp_diff - np.mean(tp_diff)) / (np.std(tp_diff) + 1e-12)
            corr = correlate(pac_norm, tp_norm, mode="full") / len(pac_diff)
            mid = len(pac_diff) - 1
            for lag in range(min_lag, max_lag + 1):
                idx = mid + lag
                if idx < len(corr) and corr[idx] < best_corr:
                    best_corr = corr[idx]
                    best_lag = lag
        except ImportError:
            def _pearson(x, y):
                xm = x - np.mean(x)
                ym = y - np.mean(y)
                denom = np.sqrt(np.sum(xm ** 2) * np.sum(ym ** 2)) + 1e-12
                return np.sum(xm * ym) / denom

            for lag in range(min_lag, max_lag + 1):
                x = pac_diff[:-lag]
                y = tp_diff[lag:]
                if len(x) < 10:
                    break
                r = _pearson(x, y)
                if r < best_corr:
                    best_corr = r
                    best_lag = lag

        if best_corr >= 0:
            best_lag = int(round(120.0 / sample_interval_minutes))

        return best_lag

    @staticmethod
    def _infer_sample_interval(df: pd.DataFrame) -> float:
        """
        从数据中自动推断采样间隔（分钟）
        
        通过计算timestamp列的中位数时间差来推断实际采样频率
        """
        if 'timestamp' not in df.columns or len(df) < 2:
            return 5.0
        
        ts = pd.to_datetime(df['timestamp'])
        diffs = ts.diff().dropna()
        
        if len(diffs) < 2:
            return 5.0
        
        median_diff = float(diffs.median().total_seconds()) / 60.0
        
        if median_diff <= 0:
            return 5.0
        
        common_intervals = [1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60]
        closest = min(common_intervals, key=lambda x: abs(x - median_diff))
        
        return float(closest)

    @staticmethod
    def _add_pac_effective_features(
        df: pd.DataFrame,
        sample_interval_minutes: float = 5.0,
    ) -> pd.DataFrame:
        """
        新增"有效PAC剂量"特征：对PAC做指数衰减加权平均

        tau = 60/120/180/240 分钟，对应不同的响应时间尺度
        alpha = 1 - exp(-sample_interval_minutes / tau_minutes)
        """
        df = df.copy()
        taus_minutes = [60, 120, 180, 240]
        pac_values = df["pac_dosage"].values
        n = len(df)

        for tau in taus_minutes:
            alpha = 1.0 - np.exp(-sample_interval_minutes / tau)
            ewma = np.zeros(n)
            ewma[0] = pac_values[0]
            for i in range(1, n):
                ewma[i] = alpha * pac_values[i] + (1 - alpha) * ewma[i - 1]
            df[f"pac_effective_tau{tau}"] = ewma

        return df


# ============================================================
# 3. 模型训练器（参数可调）
# ============================================================
class ModelTrainer:
    """模型训练器：支持从配置文件加载可调参数"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or DEFAULT_TRAIN_CONFIG.copy()
        np.random.seed(self.config.get("seed", 42))

    def _time_split(self, df: pd.DataFrame):
        """按时间顺序切分数据集"""
        train_r = self.config["split"]["train_ratio"]
        val_r = self.config["split"]["val_ratio"]
        n = len(df)
        train_end = int(n * train_r)
        val_end = int(n * (train_r + val_r))
        return df.iloc[:train_end], df.iloc[train_end:val_end], df.iloc[val_end:]

    @staticmethod
    def _evaluate(y_true, y_pred, name):
        mse = mean_squared_error(y_true, y_pred)
        rmse = np.sqrt(mse)
        mae = mean_absolute_error(y_true, y_pred)
        r2 = r2_score(y_true, y_pred)
        mape = np.mean(np.abs((y_true - y_pred) / (np.abs(y_true) + 0.001))) * 100
        return {"name": name, "rmse": rmse, "mae": mae, "r2": r2, "mape": mape}

    def _train_booster(
        self,
        df: pd.DataFrame,
        feature_cols: List[str],
        target_col: str,
        cfg_key: str,
        model_filename: str,
        features_filename: str,
        output_dir: str,
        log_label: str,
    ) -> tuple[lgb.Booster, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """P2-5 修复：train_task1/train_task2 的数据切分、参数构建、lgb训练、模型保存逻辑重复，抽取公共方法。
        返回 (model, X_train, X_val, X_test, y_train, y_val, y_test)。评估逻辑由调用方按任务差异自行实现。"""
        logger.info(log_label)
        train_df, val_df, test_df = self._time_split(df)
        X_train, y_train = train_df[feature_cols], train_df[target_col]
        X_val, y_val = val_df[feature_cols], val_df[target_col]
        X_test, y_test = test_df[feature_cols], test_df[target_col]
        logger.info("训练集: %d | 验证集: %d | 测试集: %d", len(train_df), len(val_df), len(test_df))

        cfg = self.config[cfg_key]
        params = {
            "objective": "regression",
            "metric": "rmse",
            "boosting_type": "gbdt",
            "verbosity": -1,
            "seed": self.config.get("seed", 42),
            "num_leaves": cfg["num_leaves"],
            "max_depth": cfg["max_depth"],
            "min_data_in_leaf": cfg["min_data_in_leaf"],
            "min_sum_hessian_in_leaf": cfg["min_sum_hessian_in_leaf"],
            "learning_rate": cfg["learning_rate"],
            "feature_fraction": cfg["feature_fraction"],
            "bagging_fraction": cfg["bagging_fraction"],
            "bagging_freq": cfg["bagging_freq"],
            "lambda_l1": cfg["lambda_l1"],
            "lambda_l2": cfg["lambda_l2"],
            "max_bin": 255,
            "num_threads": 4,
        }

        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        model = lgb.train(
            params,
            train_data,
            num_boost_round=cfg["num_boost_round"],
            valid_sets=[train_data, val_data],
            valid_names=["train", "valid"],
            callbacks=[
                lgb.early_stopping(
                    stopping_rounds=cfg["early_stopping_rounds"], verbose=False
                ),
                lgb.log_evaluation(period=0),
            ],
        )

        # 保存模型与特征列表
        model_path = os.path.join(output_dir, model_filename)
        model.save_model(model_path)
        with open(
            os.path.join(output_dir, features_filename),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(feature_cols, f, ensure_ascii=False, indent=2)
        logger.info("[模型保存] %s", model_path)
        return model, X_train, X_val, X_test, y_train, y_val, y_test

    def train_task1(
        self, df: pd.DataFrame, feature_cols: List[str], output_dir: str = "."
    ) -> tuple[lgb.Booster, dict[str, Any]]:
        """训练任务1：PAC加药量预测，返回模型和评估指标"""
        model, X_train, X_val, X_test, y_train, y_val, y_test = self._train_booster(
            df, feature_cols, "pac_dosage", "task1",
            "model1_pac_dosage.txt", "model1_features.json",
            output_dir, "训练任务1: PAC加药量预测",
        )

        # 评估
        eval_metrics: dict[str, Any] = {}
        for split_name, X, y in [
            ("train", X_train, y_train),
            ("val", X_val, y_val),
            ("test", X_test, y_test),
        ]:
            y_pred = model.predict(X, num_iteration=model.best_iteration)
            metrics = self._evaluate(y, y_pred, split_name)
            eval_metrics[split_name] = {
                "rmse": round(metrics["rmse"], 4),
                "mae": round(metrics["mae"], 4),
                "r2": round(metrics["r2"], 4),
                "mape": round(metrics["mape"], 2),
            }
            logger.info(
                "  [%s] RMSE=%.4f MAE=%.4f R²=%.4f MAPE=%.2f%%",
                split_name, metrics["rmse"], metrics["mae"], metrics["r2"], metrics["mape"],
            )
        return model, eval_metrics

    def train_task2(
        self, df: pd.DataFrame, feature_cols: List[str], output_dir: str = "."
    ) -> tuple[lgb.Booster, dict[str, Any]]:
        """训练任务2：出水TP变化量预测，返回模型和评估指标"""
        model, X_train, X_val, X_test, y_train, y_val, y_test = self._train_booster(
            df, feature_cols, "tp_delta", "task2",
            "model2_tp_delta.txt", "model2_features.json",
            output_dir, "训练任务2: 出水TP变化量预测",
        )

        # 评估（delta + 绝对值）
        eval_metrics: dict[str, Any] = {}
        for split_name, X, y in [
            ("train", X_train, y_train),
            ("val", X_val, y_val),
            ("test", X_test, y_test),
        ]:
            y_pred_delta = model.predict(X, num_iteration=model.best_iteration)
            metrics_delta = self._evaluate(y, y_pred_delta, f"{split_name}(delta)")
            # 绝对值评估
            current_tp = (
                X["outflow_tp"].values
                if "outflow_tp" in X.columns
                else np.zeros(len(y))
            )
            y_pred_abs = current_tp + y_pred_delta
            y_true_abs = current_tp + y.values
            metrics_abs = self._evaluate(y_true_abs, y_pred_abs, f"{split_name}(绝对TP)")
            eval_metrics[split_name] = {
                "delta": {
                    "rmse": round(metrics_delta["rmse"], 4),
                    "mae": round(metrics_delta["mae"], 4),
                    "r2": round(metrics_delta["r2"], 4),
                },
                "abs": {
                    "rmse": round(metrics_abs["rmse"], 4),
                    "mae": round(metrics_abs["mae"], 4),
                    "mape": round(metrics_abs["mape"], 2),
                },
            }
            logger.info(
                "  [%s(delta)] RMSE=%.4f MAE=%.4f R²=%.4f",
                split_name, metrics_delta["rmse"], metrics_delta["mae"], metrics_delta["r2"],
            )
            logger.info(
                "  [%s(绝对TP)] RMSE=%.4f MAE=%.4f MAPE=%.2f%%",
                split_name, metrics_abs["rmse"], metrics_abs["mae"], metrics_abs["mape"],
            )
        return model, eval_metrics

    def train_both(
        self, datasets: Dict[str, Any], output_dir: str = "."
    ) -> Dict[str, Any]:
        """同时训练两个任务，返回artifact信息和评估指标"""
        os.makedirs(output_dir, exist_ok=True)
        model1, metrics1 = self.train_task1(
            datasets["task1"], datasets["task1_features"], output_dir
        )
        model2, metrics2 = self.train_task2(
            datasets["task2"], datasets["task2_features"], output_dir
        )
        return {
            "model1": model1,
            "model2": model2,
            "model1_features": datasets["task1_features"],
            "model2_features": datasets["task2_features"],
            "model1_path": os.path.join(output_dir, "model1_pac_dosage.txt"),
            "model2_path": os.path.join(output_dir, "model2_tp_delta.txt"),
            "task1_metrics": metrics1,
            "task2_metrics": metrics2,
        }


# ============================================================
# 4. 实时推理流水线
# ============================================================
class InferencePipeline:
    """实时推理流水线"""

    RAW_COLS = RAW_COLS

    def __init__(
        self,
        model1_path: str = "model1_pac_dosage.txt",
        model2_path: str = "model2_tp_delta.txt",
        features1_path: str = "model1_features.json",
        features2_path: str = "model2_features.json",
        buffer_size: int = 120,
        sample_interval_minutes: float = 5.0,
    ):
        self.model1 = lgb.Booster(model_file=model1_path)
        self.model2 = lgb.Booster(model_file=model2_path)

        with open(features1_path, "r", encoding="utf-8") as f:
            self.features1: List[str] = json.load(f)
        with open(features2_path, "r", encoding="utf-8") as f:
            self.features2: List[str] = json.load(f)

        self.history: deque = deque(maxlen=buffer_size)
        self.sample_interval_minutes = sample_interval_minutes
        logger.info(
            "[推理初始化] 模型1特征: %d个, 模型2特征: %d个",
            len(self.features1), len(self.features2),
        )

    def _validate(self, data):
        if isinstance(data, dict):
            data = pd.DataFrame([data])
        elif isinstance(data, list):
            data = pd.DataFrame(data)
        elif not isinstance(data, pd.DataFrame):
            raise ValueError(f"不支持的数据类型: {type(data)}")
        for col in self.RAW_COLS:
            if col not in data.columns:
                raise ValueError(f"缺少字段: {col}")
        return data.copy()

    def init_history(self, historical_data):
        data = self._validate(historical_data)
        self.history.clear()
        for _, row in data.iterrows():
            self.history.append(row.to_dict())
        logger.info("[历史加载] 已加载 %d 条记录", len(self.history))

    def update(self, new_data):
        data = self._validate(new_data)
        self.history.append(data.iloc[0].to_dict())

    def _compute_features(self) -> pd.DataFrame:
        # P1-7 修复：推理时复用 FeatureEngineer 的静态方法，避免训练-推理特征计算逻辑重复。
        # 原实现独立重写了时间/交互/lag/滑动窗口/差分/PAC有效剂量特征的计算，
        # 与训练侧 FeatureEngineer.build_features 存在细微差异（如 PAC 有效剂量冷启动值不同），
        # 会导致训练-推理特征不一致。此处直接调用 FeatureEngineer 静态方法保证一致性。
        if len(self.history) < 36:
            raise ValueError(f"历史数据不足: {len(self.history)}条，需要至少36条")

        df = pd.DataFrame(list(self.history))
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        # 与 FeatureEngineer.build_features 保持相同的调用顺序
        df = FeatureEngineer._add_time_features(df)
        df = FeatureEngineer._add_interaction_features(df)
        df = FeatureEngineer._add_lag_features(df)
        df = FeatureEngineer._add_rolling_features(df)
        df = FeatureEngineer._add_diff_features(df)
        df = FeatureEngineer._add_pac_effective_features(df, self.sample_interval_minutes)

        # 任务1特有特征（与 build_features 中一致）
        df["outflow_tp_lag1_above_target"] = (df["outflow_tp_lag1"] > 0.3).astype(int)
        df["outflow_tp_lag1_deviation"] = df["outflow_tp_lag1"] - 0.3

        # 只返回最后一行（当前时刻）的特征
        return df.iloc[[-1]].copy()

    def predict(self) -> Dict[str, Any]:
        if len(self.history) < 36:
            return {
                "status": "error",
                "message": f"历史数据不足: {len(self.history)}条",
            }

        features_df = self._compute_features()
        X1 = features_df[self.features1]
        X2 = features_df[self.features2]

        pac_pred = self.model1.predict(X1)[0]
        tp_delta_pred = self.model2.predict(X2)[0]
        current_tp = features_df["outflow_tp"].iloc[0]

        return {
            "status": "ok",
            "timestamp": str(features_df["timestamp"].iloc[0]),
            "pac_dosage_prediction": round(float(pac_pred), 2),
            "tp_delta_prediction": round(float(tp_delta_pred), 4),
            "current_outflow_tp": round(float(current_tp), 3),
            "next_outflow_tp_prediction": round(float(current_tp + tp_delta_pred), 3),
        }

    def update_and_predict(self, new_data) -> Dict[str, Any]:
        self.update(new_data)
        return self.predict()


# ============================================================
# 5. 辅助函数：从数据库样本构建DataFrame
# ============================================================
def samples_to_dataframe(
    samples: List[Dict[str, Any]],
) -> pd.DataFrame:
    """
    将现有系统的 model_training_samples 转换为 wwtp_ai_engine 可用的 DataFrame

    samples: 列表，每个元素是 {sample_time, values, target_value, ...}
    values 中的 key 需要映射到 RAW_COLS
    """
    rows = []
    for sample in samples:
        values = sample.get("values", {})
        row = {"timestamp": sample.get("sample_time")}
        for raw_col in RAW_COLS:
            if raw_col == "timestamp":
                continue
            # 优先用 RAW_COL 的 key，其次用 TAG 的 key
            val = values.get(raw_col)
            if val is None:
                tag_key = RAW_TO_TAG_MAP.get(raw_col)
                if tag_key:
                    val = values.get(tag_key)
            row[raw_col] = val
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.sort_values("timestamp").reset_index(drop=True)

    # 数值转换
    for col in RAW_COLS:
        if col != "timestamp":
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 简单清洗（和 DataImporter._clean 类似，但这里只做 NaN 处理）
    df = df.dropna(subset=[c for c in RAW_COLS if c != "timestamp"]).reset_index(
        drop=True
    )
    return df


def normalize_training_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    """将用户传入的配置归一化为标准训练配置"""
    base = DEFAULT_TRAIN_CONFIG.copy()
    if not isinstance(raw, dict):
        return base

    # 全局参数
    split = raw.get("split", {})
    if isinstance(split, dict):
        base["split"]["train_ratio"] = _clamp_float(
            split.get("train_ratio"), base["split"]["train_ratio"], 0.1, 0.9
        )
        base["split"]["val_ratio"] = _clamp_float(
            split.get("val_ratio"), base["split"]["val_ratio"], 0.05, 0.5
        )
    base["seed"] = _clamp_int(raw.get("seed"), base["seed"], 0, 999999)

    tp_hrt = raw.get("tp_hrt_minutes")
    if tp_hrt is not None:
        base["tp_hrt_minutes"] = _clamp_float(tp_hrt, None, 1, 1440) if tp_hrt > 0 else None

    # Task1 参数
    base["task1"] = _normalize_task_config(raw.get("task1", {}), base["task1"])
    # Task2 参数
    base["task2"] = _normalize_task_config(raw.get("task2", {}), base["task2"])

    return base


def _normalize_task_config(raw_task: Dict[str, Any], base_task: Dict[str, Any]) -> Dict[str, Any]:
    result = base_task.copy()
    if not isinstance(raw_task, dict):
        return result
    for key in result:
        if key in raw_task:
            if key in (
                "num_leaves",
                "max_depth",
                "min_data_in_leaf",
                "num_boost_round",
                "early_stopping_rounds",
                "bagging_freq",
            ):
                result[key] = _clamp_int(raw_task[key], result[key], 1, 10000)
            elif key in ("learning_rate", "feature_fraction", "bagging_fraction"):
                result[key] = _clamp_float(raw_task[key], result[key], 0.001, 1.0)
            elif key in ("lambda_l1", "lambda_l2", "min_sum_hessian_in_leaf"):
                result[key] = _clamp_float(raw_task[key], result[key], 0.0, 1000.0)
    return result


def _clamp_float(value: Any, default: float, min_val: float, max_val: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(number):
        return default
    return min(max(number, min_val), max_val)


def _clamp_int(value: Any, default: int, min_val: int, max_val: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return min(max(number, min_val), max_val)
