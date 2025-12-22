import json
import os
import traceback
import time
from pathlib import Path
from typing import Any, List, Dict, Tuple

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType
from app.helper.mediaserver import MediaServerHelper


class CloudTransferStrm(_PluginBase):
    # 插件名称
    plugin_name = "转移触发Strm"
    # 插件描述
    plugin_desc = "转移云盘文件触发Strm生成。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/thsrite/MoviePilot-Plugins/main/icons/cloudcompanion.png"
    # 插件版本
    plugin_version = "1.0.1"
    # 插件作者
    plugin_author = "ahjsrhj"
    # 作者主页
    author_url = "https://github.com/ahjsrhj"
    # 插件配置项ID前缀
    plugin_config_prefix = "CloudTransferStrm_"
    # 加载顺序
    plugin_order = 26
    # 可使用的用户级别
    auth_level = 1
    test = 1

    # 私有属性
    _enabled = False
    _monitor_confs = None
    _refresh_emby = False
    # 配置字典: key为local_dir, value为包含strm_dir和alist_host的字典
    _monitor_configs = {}

    mediaserver_helper = None

    def init_plugin(self, config: dict = None):
        """
        初始化插件
        """
        # 清空配置
        self._monitor_configs = {}
        self.mediaserver_helper = MediaServerHelper()

        # 初始化配置，确保_monitor_confs始终是字符串
        if config:
            self._enabled = config.get("enabled", False)
            self._refresh_emby = config.get("refresh_emby")
            monitor_confs_value = config.get("monitor_confs")
            # 确保是字符串类型
            self._monitor_confs = (
                str(monitor_confs_value) if monitor_confs_value is not None else ""
            )
        else:
            # 如果config为None，确保使用默认值
            self._enabled = False
            self._monitor_confs = ""

        # 如果未启用，直接返回
        if not self._enabled:
            return

        # 双重保险：确保_monitor_confs是字符串类型且不为None
        if self._monitor_confs is None:
            self._monitor_confs = ""
        else:
            self._monitor_confs = str(self._monitor_confs)

        # 如果没有配置内容，直接返回
        if not self._monitor_confs:
            logger.warning("插件已启用但未配置监控目录，请配置 monitor_confs")
            return

        # 解析目录配置
        # 格式: local_dir#strm_dir#alist_host
        # 此时_monitor_confs已经确保是字符串类型
        try:
            monitor_conf_lines = self._monitor_confs.split("\n")
        except AttributeError:
            logger.error(
                f"monitor_confs类型错误: {type(self._monitor_confs)}, 值: {self._monitor_confs}"
            )
            # 强制转换为字符串
            self._monitor_confs = (
                str(self._monitor_confs) if self._monitor_confs is not None else ""
            )
            monitor_conf_lines = self._monitor_confs.split("\n")
        for monitor_conf in monitor_conf_lines:
            # 跳过空行
            if not monitor_conf or not monitor_conf.strip():
                continue
            # 跳过注释
            if str(monitor_conf).strip().startswith("#"):
                continue

            # 检查格式
            parts = str(monitor_conf).strip().split("#")
            if len(parts) != 3:
                logger.error(
                    f"配置格式错误，应为: local_dir#strm_dir#alist_host，当前: {monitor_conf}"
                )
                continue

            local_dir = parts[0].strip()
            strm_dir = parts[1].strip()
            alist_host = parts[2].strip()

            if not local_dir or not strm_dir or not alist_host:
                logger.error(f"配置项不能为空: {monitor_conf}")
                continue

            # 标准化路径：确保local_dir不以斜杠结尾（除非是根路径）
            if local_dir != "/" and local_dir.endswith("/"):
                local_dir = local_dir.rstrip("/")

            # 存储配置
            self._monitor_configs[local_dir] = {
                "strm_dir": strm_dir,
                "alist_host": alist_host,
            }
            logger.info(
                f"加载监控配置: local_dir={local_dir}, strm_dir={strm_dir}, alist_host={alist_host}"
            )

    @eventmanager.register(EventType.TransferComplete)
    def transfer_complete(self, event: Event = None):
        """
        监听入库成功通知，生成strm文件
        """
        if not self._enabled:
            return

        if not event or not event.event_data:
            return

        try:
            event_data = event.event_data
            # event_data 是字典，transferinfo 是 TransferInfo 对象
            if isinstance(event_data, dict):
                transferinfo = event_data.get("transferinfo")
            else:
                transferinfo = getattr(event_data, "transferinfo", None)

            if not transferinfo:
                logger.warning("TransferComplete事件缺少transferinfo")
                return

            # transferinfo 是 TransferInfo 对象（Pydantic模型），使用属性访问
            target_item = transferinfo.target_item
            if not target_item:
                logger.warning("TransferComplete事件缺少target_item")
                return

            # target_item 是 FileItem 对象，使用属性访问
            target_path = str(target_item.path)
            logger.info(f"收到入库成功通知，目标文件：{target_path}")

            # 只处理媒体文件
            if Path(target_path).suffix.lower() not in [
                ext.strip() for ext in settings.RMT_MEDIAEXT
            ]:
                logger.debug(f"{target_path} 不是媒体文件，跳过处理")
                return

            # 查找匹配的监控配置
            matched_local_dir = None
            for local_dir in self._monitor_configs.keys():
                # 检查target_path是否以local_dir开头
                # 需要确保匹配的是完整路径段，而不是部分匹配
                if target_path == local_dir or target_path.startswith(local_dir + "/"):
                    # 选择最长的匹配路径（避免子路径匹配到父路径）
                    if not matched_local_dir or len(local_dir) > len(matched_local_dir):
                        matched_local_dir = local_dir

            if not matched_local_dir:
                logger.debug(f"未找到匹配的监控配置: {target_path}")
                return

            # 获取配置
            config = self._monitor_configs[matched_local_dir]
            strm_dir = config["strm_dir"]
            alist_host = config["alist_host"]

            # 计算strm文件路径
            # 去掉local_dir 前缀，保留剩余路径
            if target_path == matched_local_dir:
                # 如果target_path就是local_dir本身，则relative_path为空
                relative_path = ""
            else:
                # 去掉local_dir和后面的斜杠
                relative_path = target_path[len(matched_local_dir) :]
                if relative_path.startswith("/"):
                    relative_path = relative_path[1:]
            # 构建strm文件路径
            strm_file_path = os.path.join(strm_dir, relative_path)
            # 将文件扩展名改为.strm
            strm_file_path = os.path.splitext(strm_file_path)[0] + ".strm"

            # 生成strm文件内容: alist_host + target_path
            strm_content = alist_host + target_path

            # 创建strm文件
            self.__create_strm_file(strm_file=strm_file_path, strm_content=strm_content)

            logger.info(f"成功生成strm文件: {strm_file_path} -> {strm_content}")

            # 通知emby刷新
            if self._refresh_emby:
                time.sleep(0.1)
                self.__refresh_emby_file(strm_file_path)
            return True


        except Exception as e:
            logger.error(f"处理入库成功通知失败: {str(e)} - {traceback.format_exc()}")

    def __create_strm_file(self, strm_file: str, strm_content: str):
        """
        生成strm文件
        :param strm_file: strm文件路径
        :param strm_content: strm文件内容
        """
        try:
            # 确保目录存在
            strm_file_path = Path(strm_file)
            if not strm_file_path.parent.exists():
                logger.info(f"创建目标文件夹 {strm_file_path.parent}")
                os.makedirs(strm_file_path.parent, exist_ok=True)

            # 写入.strm文件
            with open(strm_file, "w", encoding="utf-8") as f:
                f.write(strm_content)

            logger.info(f"创建strm文件成功: {strm_file} -> {strm_content}")
            return True
        except Exception as e:
            logger.error(f"创建strm文件失败 {strm_file} -> {str(e)}")
            return False

    def __refresh_emby_file(self, strm_file: str):
        """
        通知emby刷新文件
        """
        emby_servers = self.mediaserver_helper.get_services(type_filter="emby")
        if not emby_servers:
            logger.error("未配置Emby媒体服务器")
            return

        # strm_file = self.__get_path(paths=self._emby_paths, file_path=strm_file)
        for emby_name, emby_server in emby_servers.items():
            emby = emby_server.instance
            self._EMBY_USER = emby_server.instance.get_user()
            self._EMBY_APIKEY = emby_server.config.config.get("apikey")
            self._EMBY_HOST = emby_server.config.config.get("host")

            logger.info(f"开始通知媒体服务器 {emby_name} 刷新增量文件 {strm_file}")
            try:
                res = emby.post_data(
                    url=f'[HOST]emby/Library/Media/Updated?api_key=[APIKEY]&reqformat=json',
                    data=json.dumps({
                        "Updates": [
                            {
                                "Path": strm_file,
                                "UpdateType": "Created",
                            }
                        ]
                    }),
                    headers={
                        "Content-Type": "application/json"
                    }
                )
                if res and res.status_code in [200, 204]:
                    return True
                else:
                    logger.error(f"通知媒体服务器 {emby_name} 刷新新增文件 {strm_file} 失败，错误码：{res.status_code}")
                    return False
            except Exception as err:
                logger.error(f"通知媒体服务器刷新新增文件失败：{str(err)}")
            return False

    def get_state(self) -> bool:
        return self._enabled

    def stop_service(self):
        """
        停止插件服务
        """
        # 清空配置
        self._monitor_configs = {}
        self._enabled = False
        logger.info("插件服务已停止")

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "refresh_emby",
                                            "label": "刷新媒体库（Emby）",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "monitor_confs",
                                            "label": "目录配置",
                                            "rows": 5,
                                            "placeholder": "MoviePilot中云盘挂载本地的路径#MoviePilot中strm生成路径#alist strm目录前缀\n例如：/189person/movie-linked#/StrmMedia/电影#https://openlist.home.imrhj.cn/d",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "monitor_confs": "",
            "refresh_emby": False,
        }

    def get_page(self) -> List[dict]:
        pass
