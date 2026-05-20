'''
 =======================================================================
 ····Y88b···d88P················888b·····d888·d8b·······················
 ·····Y88b·d88P·················8888b···d8888·Y8P·······················
 ······Y88o88P··················88888b·d88888···························
 ·······Y888P··8888b···88888b···888Y88888P888·888·88888b·····d88b·······
 ········888······"88b·888·"88b·888·Y888P·888·888·888·"88b·d88P"88b·····
 ········888···d888888·888··888·888··Y8P··888·888·888··888·888··888·····
 ········888··888··888·888··888·888···"···888·888·888··888·Y88b·888·····
 ········888··"Y888888·888··888·888·······888·888·888··888··"Y88888·····
 ·······························································888·····
 ··························································Y8b·d88P·····
 ···························································"Y88P"······
 =======================================================================

 -----------------------------------------------------------------------
Author       : 焱铭
Date         : 2025-04-22 12:43:54 +0800
LastEditTime : 2025-04-29 17:37:32 +0800
Github       : https://github.com/YanMing-lxb/
FilePath     : /egasp/src/egasp/validate.py
Description  : 
 -----------------------------------------------------------------------
'''
import logging

class Validate:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    def type_value(self, query_type:str, default_value:str='volume')->str:
        if query_type in ['volume', 'v', 'mass', 'm', '']:
            if query_type == '':
                self.logger.info(f"未输入查询类型，将使用默认类型 {default_value}")
                return default_value
            if query_type == 'v':
                return 'volume'
            if query_type == 'm':
                return 'mass'
            return query_type
        else:
            self.logger.warning(f"无效查询类型，将使用默认值 {default_value}")
            return default_value
    def input_value(self, value, min_val=None, max_val=None):
        try:
            if min_val is not None and value < min_val:
                self.logger.warning(f"输入值不能小于 {min_val}，请重新输入。")
            if max_val is not None and value > max_val:
                self.logger.warning(f"输入值不能大于 {max_val}，请重新输入。")
            return value
        except ValueError:
            self.logger.warning("请输入有效的数字，请重新输入。")

