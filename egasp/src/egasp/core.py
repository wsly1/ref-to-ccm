import logging
import sys
import bisect
from typing import Tuple, Union, Optional
from functools import lru_cache
import numpy as np

from egasp.data.egasp_data import EGP
from egasp.validate import Validate


# 类级别的缓存数据
_temp_nodes = list(range(-35, 126, 5))
_conc_nodes = [round(0.1 + i * 0.1, 1) for i in range(9)]

# 类级别的numpy数据数组
_rho_array = None
_cp_array = None
_k_array = None
_mu_array = None
_array_map = None

def _init_class_data():
    """初始化类级别的数据数组"""
    global _rho_array, _cp_array, _k_array, _mu_array, _array_map
    if _rho_array is None:
        _rho_array = np.array(EGP['rho'], dtype=np.float64)
        _cp_array = np.array(EGP['cp'], dtype=np.float64)
        _k_array = np.array(EGP['k'], dtype=np.float64)
        _mu_array = np.array(EGP['mu'], dtype=np.float64)
        _array_map = {
            'rho': _rho_array,
            'cp': _cp_array,
            'k': _k_array,
            'mu': _mu_array
        }


@lru_cache(maxsize=1024)
def _cached_prop_single(temp: float, conc: float, egp_key: str) -> Optional[float]:
    """缓存的单个温度和浓度值计算（静态函数，避免内存泄漏）"""
    _init_class_data()
    
    # 查找节点索引
    t_lower_idx, t_upper_idx = _find_nearest_nodes_static(_temp_nodes, temp, "温度")
    c_lower_idx, c_upper_idx = _find_nearest_nodes_static(_conc_nodes, conc, "浓度")

    data_array = _array_map[egp_key]
    
    # 提取四个角点数据
    v11 = data_array[t_lower_idx][c_lower_idx]
    v12 = data_array[t_lower_idx][c_upper_idx]
    v21 = data_array[t_upper_idx][c_lower_idx]
    v22 = data_array[t_upper_idx][c_upper_idx]

    # 检查数据有效性
    if np.isnan(v11) or np.isnan(v21) or np.isnan(v12) or np.isnan(v22):
        return None
    
    # 执行插值计算
    t_lower, t_upper = _temp_nodes[t_lower_idx], _temp_nodes[t_upper_idx]
    c_lower, c_upper = _conc_nodes[c_lower_idx], _conc_nodes[c_upper_idx]

    # 处理不同的插值情况
    if t_lower == t_upper and c_lower == c_upper:
        result = v11
    elif t_lower == t_upper:
        result = _interpolate_linear_static(c_lower, v11, c_upper, v12, conc)
    elif c_lower == c_upper:
        result = _interpolate_linear_static(t_lower, v11, t_upper, v21, temp)
    else:
        v1 = _interpolate_linear_static(c_lower, v11, c_upper, v12, conc)
        v2 = _interpolate_linear_static(c_lower, v21, c_upper, v22, conc)
        result = _interpolate_linear_static(t_lower, v1, t_upper, v2, temp)

    return result


@staticmethod
def _interpolate_linear_static(x1: float, y1: float, x2: float, y2: float, x: float) -> float:
    """静态线性插值计算"""
    try:
        return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    except ZeroDivisionError:
        raise RuntimeError(f"插值节点间距为零 x1={x1}, x2={x2}")


def _find_nearest_nodes_static(nodes: list, value: float, name: str) -> Tuple[int, int]:
    """静态查找目标值在节点序列中的相邻节点索引"""
    try:
        idx = bisect.bisect_right(nodes, value) - 1
        lower_idx = max(idx, 0)
        upper_idx = min(bisect.bisect_left(nodes, value), len(nodes) - 1)

        if not (nodes[lower_idx] <= value <= nodes[upper_idx]):
            raise ValueError(f"{name} {value} 超出有效范围 [{nodes[0]}, {nodes[-1]}]")

        return lower_idx, upper_idx
    except IndexError as e:
        raise RuntimeError(f"节点索引错误: {str(e)}")


class EGASP:

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.validate = Validate()
        
        # 初始化类级别数据
        _init_class_data()
        
        # 实例级别的数据引用（用于日志等）
        self.temp_nodes = _temp_nodes
        self.conc_nodes = _conc_nodes
        self.rho_array = _rho_array
        self.cp_array = _cp_array
        self.k_array = _k_array
        self.mu_array = _mu_array
        self.array_map = _array_map

    @staticmethod
    def concentration_type_to_chinese(concentration_type: str) -> str:
        """将浓度类型名称符号 (如 volume/v 和 mass/m) 转换成对应的中文名称"""
        type_mapping = {
            'volume': '体积浓度',
            'mass': '质量浓度',
            'rho': '密度',
            'cp': '比热容',
            'k': '导热系数',
            'mu': '动力粘度'
        }
        
        if concentration_type not in type_mapping:
            raise ValueError(f"不支持的浓度类型: {concentration_type}，支持的类型有: volume/v, mass/m")
            
        return type_mapping[concentration_type]

    @staticmethod
    def _interpolate_linear(x1: float, y1: float, x2: float, y2: float, x: float) -> float:
        """执行线性插值计算"""
        return _interpolate_linear_static(x1, y1, x2, y2, x)

    def _error_exit(self, msg: str = None) -> None:
        """记录错误信息并终止程序执行"""
        if msg:
            self.logger.error(msg)
        sys.exit()

    def _find_nearest_nodes(self, nodes: list, value: float, name: str) -> Tuple[int, int]:
        """查找目标值在节点序列中的相邻节点索引"""
        try:
            return _find_nearest_nodes_static(nodes, value, name)
        except (ValueError, RuntimeError) as e:
            self._error_exit(str(e))

    def prop(self, temp: Union[float, np.ndarray], conc: float, egp_key: str) -> Union[float, np.ndarray]:
        """根据温度和浓度计算指定物性参数"""
        if egp_key not in ['rho', 'cp', 'k', 'mu']:
            self._error_exit(f"无效物性参数 {egp_key}，可选值: rho/cp/k/mu")

        # 处理numpy数组输入 - 使用向量化
        if isinstance(temp, np.ndarray):
            # 向量化处理
            result = np.vectorize(lambda t: _cached_prop_single(t, conc, egp_key), otypes=[np.float64])(temp)
            return result / 1000 if egp_key == "mu" else result
        else:
            result = _cached_prop_single(temp, conc, egp_key)
            # 检查数据缺失警告
            if result is None:
                self._log_missing_data_warning(temp, conc, egp_key)
            return result / 1000 if egp_key == "mu" else result

    def _log_missing_data_warning(self, temp: float, conc: float, egp_key: str):
        """记录数据缺失警告"""
        t_lower_idx, t_upper_idx = self._find_nearest_nodes(self.temp_nodes, temp, "温度")
        c_lower_idx, c_upper_idx = self._find_nearest_nodes(self.conc_nodes, conc, "浓度")
        
        data_array = self.array_map[egp_key]
        v11 = data_array[t_lower_idx][c_lower_idx]
        v12 = data_array[t_lower_idx][c_upper_idx]
        v21 = data_array[t_upper_idx][c_lower_idx]
        v22 = data_array[t_upper_idx][c_upper_idx]
        
        if np.isnan(v11) or np.isnan(v21):
            self.logger.warning(f"数据库在体积浓度 {self.conc_nodes[c_lower_idx]} 下，温度 {self.temp_nodes[t_lower_idx]} ~ {self.temp_nodes[t_upper_idx]} 的范围内[red]{self.concentration_type_to_chinese(egp_key)}[/red]数据缺失")
        if np.isnan(v12) or np.isnan(v22):
            self.logger.warning(f"数据库在体积浓度 {self.conc_nodes[c_upper_idx]} 下，温度 {self.temp_nodes[t_lower_idx]} ~ {self.temp_nodes[t_upper_idx]} 的范围内[red]{self.concentration_type_to_chinese(egp_key)}[/red]数据缺失")

    def fb_props(self, query: float, query_type: str = 'volume') -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        """根据浓度查询冰点和沸点相关物性参数"""
        if query_type not in ['mass', 'volume']:
            self._error_exit(f"无效查询类型 {query_type}，必须为 'mass' 或 'volume'")

        data = EGP.get('fb')

        # 排序数据
        sort_key = 1 if query_type == 'volume' else 0
        sorted_data = sorted(data, key=lambda x: x[sort_key])
        sorted_values = [item[sort_key] for item in sorted_data]

        # 查找相邻数据点
        try:
            idx = bisect.bisect_left(sorted_values, query)
            if idx == 0 or idx == len(sorted_data):
                self._error_exit(f"浓度 {query} 超出数据范围 [{sorted_values[0]}, {sorted_values[-1]}]")

            prev, curr = sorted_data[idx - 1], sorted_data[idx]
            p_val, c_val = prev[sort_key], curr[sort_key]

            if not (p_val <= query <= c_val):
                self._error_exit(f"浓度 {query} 不在相邻数据点之间 [{p_val}, {c_val}]")
        except Exception as e:
            self._error_exit(f"数据查询失败: {str(e)}")

        # 解包数据
        m1, v1, f1, b1 = prev
        m2, v2, f2, b2 = curr
        
        # 定义需要检查的数据字段
        field_names = ["质量浓度", "体积浓度", "冰点", "沸点"]
        
        # 检查数据完整性 - 逐个检查每个数据点
        for i, (prev_data, curr_data) in enumerate(zip(prev, curr)):
            if None in (prev_data, curr_data):
                if query_type == 'volume':
                    self.logger.warning(f"数据库在{self.concentration_type_to_chinese(query_type)} {v1:.2f} ~ {v2:.2f} 的范围内{field_names[i]}数据缺失")
                else:
                    self.logger.warning(f"数据库在{self.concentration_type_to_chinese(query_type)} {m1:.2f} ~ {m2:.2f} 的范围内{field_names[i]}数据缺失")

        # 如果某个数据缺失则不对该数据进行插值，只返回None
        if query_type == 'volume':
            mass = self._interpolate_linear(v1, m1, v2, m2, query) if None not in [v1, m1, v2, m2] else None
            volume = query
            freezing = self._interpolate_linear(v1, f1, v2, f2, query) if None not in [v1, f1, v2, f2] else None
            boiling = self._interpolate_linear(v1, b1, v2, b2, query) if None not in [v1, b1, v2, b2] else None
        else:
            volume = self._interpolate_linear(m1, v1, m2, v2, query) if None not in [m1, v1, m2, v2] else None
            mass = query
            freezing = self._interpolate_linear(m1, f1, m2, f2, query) if None not in [m1, f1, m2, f2] else None
            boiling = self._interpolate_linear(m1, b1, m2, b2, query) if None not in [m1, b1, m2, b2] else None

        return (mass, volume, freezing, boiling)


    def props(self, query_temp: float, query_type: str = 'volume', query_value: float = 0.5) -> tuple:
        """根据输入的查询类型、浓度和温度，计算乙二醇水溶液的相关属性。"""
        query_type = self.validate.type_value(query_type)
        query_value = self.validate.input_value(query_value, min_val=0.1, max_val=0.9)
        query_temp = self.validate.input_value(query_temp, min_val=-35, max_val=125)

        mass, volume, freezing, boiling = self.fb_props(query_value, query_type=query_type)
        rho = self.prop(temp=query_temp, conc=volume, egp_key='rho')
        cp = self.prop(temp=query_temp, conc=volume, egp_key='cp')
        k = self.prop(temp=query_temp, conc=volume, egp_key='k')
        mu = self.prop(temp=query_temp, conc=volume, egp_key='mu')

        return mass, volume, freezing, boiling, rho, cp, k, mu
