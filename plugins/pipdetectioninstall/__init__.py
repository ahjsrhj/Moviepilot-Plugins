import inspect
import os
import subprocess
from pathlib import Path
from typing import Any, List, Dict, Tuple, Optional

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.core.plugin import PluginManager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import SystemConfigKey
from threading import Lock

lock = Lock()


class PipDetectionInstall(_PluginBase):
    # 插件名称
    plugin_name = "PIP依赖包检测与安装"
    # 插件描述
    plugin_desc = "解决MoviePilot 的PIP依赖包下载超时失败、不支持代理导致下载缓慢等问题。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/Aqr-K/MoviePilot-Plugins/main/icons/PyPI.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "Aqr-K"
    # 作者主页
    author_url = "https://github.com/Aqr-K"
    # 插件配置项ID前缀
    plugin_config_prefix = "pipdetectioninstall_"
    # 加载顺序
    plugin_order = 11
    # 可使用的用户级别
    auth_level = 1

    PluginManager = PluginManager()

    _onlyonce: bool = False

    _proxy_enabled: bool = False
    _index_url_enabled: bool = False
    _index_url: dict = {}

    _event = None
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        """
        初始化插件
        """
        if not config:
            return False
        if config:
            self._onlyonce = config.get("onlyonce", False)
            self._proxy_enabled = config.get("proxy_enabled", False)
            self._index_url_enabled = config.get("index_url_enabled", False)
            self._index_url = config.get("index_url") or {}

            self.__update_config()
        # 仅允许通过前端提交运行
        if self.__check_stack_contain_save_config_request():
            if self._onlyonce:
                self.run()

    def get_state(self):
        return self._onlyonce

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        mirror_sites = ['https://mirrors.aliyun.com/pypi/simple',
                        'https://pypi.tuna.tsinghua.edu.cn/simple',
                        'https://pypi.mirrors.ustc.edu.cn/simple',
                        'https://pypi.doubanio.com/simple'
                        ]

        default_items = [{'title': site, 'value': site} for site in mirror_sites]

        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'props': {
                            'align': 'center',
                        },
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3,
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立刻运行一次',
                                            'hint': '一次性任务；运行后自动关闭',
                                            'persistent-hint': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3,
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'proxy_enabled',
                                            'label': '启用代理访问',
                                            'hint': '开启后将使用代理下载依赖包',
                                            'persistent-hint': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3,
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'index_url_enabled',
                                            'label': '启用自定义镜像站',
                                            'hint': '启用后，自定义镜像站才会生效',
                                            'persistent-hint': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'warning',
                                            'variant': 'tonal',
                                            'style': 'white-space: pre-line; width: fit-content;',
                                            'text': '问题反馈：',
                                        },
                                        'content': [
                                            {
                                                'component': 'a',
                                                'props': {
                                                    'href': 'https://github.com/Aqr-K/MoviePilot-Plugins/issues/new',
                                                    'target': '_blank'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'u',
                                                        'text': 'ISSUES'
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VCombobox',
                                        'props': {
                                            'model': 'index_url',
                                            'label': '自定义镜像站URL',
                                            'placeholder': '默认：https://pypi.org/simple',
                                            'items': default_items,
                                            'hint': '将默认的pypi官网替换成镜像站点；支持手动输入',
                                            'persistent-hint': True,
                                            'clearable': True,
                                            'active': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'style': 'white-space: pre-line;',
                                            'text': '注意：\n'
                                                    '1、本插件为纯手动运行，主要是 MP-v1.0+ 的pip下载超时、不支持使用代理下载等问题的填坑；\n'
                                                    '2、代理与镜像是允许同时启用的，优先级：镜像站 > 代理 > 直连。\n'
                                        },
                                    },
                                ]
                            },
                        ]
                    }
                ]
            },
        ], {
            'onlyonce': False,
            'proxy_enabled': False,
            'index_url_enabled': False,
            'index_url': None,
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))

    """ init """

    def run(self):
        """
        启动
        """
        try:
            # 已经写入数据库中
            installed_apps = self.systemconfig.get(SystemConfigKey.UserInstalledPlugins) or []
            # 本地插件目录
            for plugin_id in installed_apps:
                with lock:
                    # 插件本地是否存在
                    if self.PluginManager.is_plugin_exists(pid=plugin_id):
                        plugin_dir = Path(settings.ROOT_PATH) / "app" / "plugins" / plugin_id.lower()
                        requirements_file = plugin_dir / "requirements.txt"
                        if requirements_file.exists():
                            logger.debug(f"[{plugin_id}] - 找到插件依赖包文件地址 - {requirements_file}")
                            # Todo：优化成，根据判断决定，暂时为有requirements就执行
                            # if self.check_plugin_requirements(plugin_id=plugin_id) is False:
                            if True:
                                self.__pip_install_with_fallback(requirements_file=requirements_file,
                                                                 plugin_id=plugin_id)
                        else:
                            logger.info(f"[{plugin_id}] 插件不需要第三方依赖，跳过重载检测")
                    # 插件本地不存在
                    else:
                        logger.warning(f"[{plugin_id}] 插件本地不存在，无法检测依赖包")
        except Exception as e:
            logger.error(f"插件运行失败 - {e}", exc_info=True)

        finally:
            self._onlyonce = False
            self.__update_config()

    """ 环境依赖判断 """

    @staticmethod
    def check_plugin_requirements(plugin_id: str) -> Optional[bool]:
        """
        重载插件判断import是否成功
        """
        try:
            # Todo：调用现成的方法无法获取import失败的插件，待优化
            # self.PluginManager.reload_plugin(plugin_id=plugin_id)
            logger.info(f"[{plugin_id}] 插件重载成功")
            return True
        except ImportError:
            logger.warning(f"[{plugin_id}] 插件重载失败，重新获取pip依赖包")
            return False
        except Exception as e:
            logger.error(f"[{plugin_id}] 插件重载异常，无法判断是否需要重新获取pip依赖包 - {e}", exc_info=True)
            return None

    """ 插件调用栈检测 """

    @classmethod
    def __check_stack_contain_method(cls, package_name: str, function_name: str) -> bool:
        """
        判断调用栈是否包含指定的方法
        """
        if not package_name or not function_name:
            return False
        package_path = package_name.replace('.', os.sep)
        for stack in inspect.stack():
            if not stack or not stack.filename:
                continue
            if stack.function != function_name:
                continue
            if stack.filename.endswith(f"{package_path}.py") or stack.filename.endswith(
                    f"{package_path}{os.sep}__init__.py"):
                return True
        return False

    @classmethod
    def __check_stack_contain_save_config_request(cls) -> bool:
        """
        判断调用栈是否包含“插件配置保存”接口
        """
        return cls.__check_stack_contain_method('app.api.endpoints.plugin', 'set_plugin_config')

    """ 更新 """

    def __update_config(self):
        """
        更新配置
        """
        config = {
            "onlyonce": self._onlyonce,
            "proxy_enabled": self._proxy_enabled,
            "index_url_enabled": self._index_url_enabled,
            "index_url": self._index_url,
        }
        self.update_config(config)

    """ PIP下载 """

    @staticmethod
    def execute_with_subprocess(pip_command: list) -> Tuple[bool, str]:
        """
        执行命令并捕获标准输出和错误输出，记录日志。

        :param pip_command: 要执行的命令，以列表形式提供
        :return: (命令是否成功, 输出信息或错误信息)
        """
        try:
            # 使用 subprocess.run 捕获标准输出和标准错误
            result = subprocess.run(pip_command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # 合并 stdout 和 stderr
            output = result.stdout + result.stderr
            return True, output
        except subprocess.CalledProcessError as e:
            error_message = f"命令：{' '.join(pip_command)}，执行失败，错误信息：{e.stderr.strip()}"
            return False, error_message
        except Exception as e:
            error_message = f"未知错误，命令：{' '.join(pip_command)}，错误：{str(e)}"
            return False, error_message

    def __pip_install_with_fallback(self, requirements_file: Path, plugin_id: str) -> Tuple[bool, str]:
        """
        使用自动降级策略，PIP 安装依赖，优先级依次为镜像站、代理、直连
        :param requirements_file: 依赖的 requirements.txt 文件路径
        :return: (是否成功, 错误信息)
        """
        # 降级策略
        strategies = []

        # 添加策略到列表中
        if self._index_url_enabled and self._index_url:
            index_url = self._index_url.get("value", "https://pypi.org/simple")
            strategies.append(("镜像站", ["pip", "install", "-r", str(requirements_file), "-i", index_url]))
        if self._proxy_enabled and settings.PROXY_HOST:
            strategies.append(
                ("代理", ["pip", "install", "-r", str(requirements_file), "--proxy", settings.PROXY_HOST]))
        strategies.append(("直连", ["pip", "install", "-r", str(requirements_file)]))

        # 遍历策略进行安装
        for strategy_name, pip_command in strategies:
            logger.debug(f"[PIP] 尝试使用策略：{strategy_name} 安装 [{plugin_id}] 插件依赖，命令：{' '.join(pip_command)}")
            success, message = self.execute_with_subprocess(pip_command)
            if success:
                logger.debug(f"[PIP] 策略：{strategy_name} 安装 [{plugin_id}] 插件依赖成功，输出：{message}")
                return True, message
            else:
                logger.error(f"[PIP] 策略：{strategy_name} 安装 [{plugin_id}] 插件依赖失败，错误信息：{message}")
