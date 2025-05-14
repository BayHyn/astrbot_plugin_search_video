import os
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.components import  Video
from astrbot.core.utils.session_waiter import SessionController, session_waiter
from astrbot import logger
from .api import VideoAPI

@register(
    "nonebot_plugin_search_video",
    "Zhalslar",
    "视频搜索",
    "1.0.0",
    "https://github.com/Zhalslar/nonebot_plugin_search_video",
)
class VideoPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        # 哔哩哔哩限制的最大视频时长（默认8分钟），单位：秒
        self.max_duration: int = config.get("max_duration", 600)
        # B站cookie
        self.cookie: str = config.get("cookie", "")
        # 实例化api
        self.api = VideoAPI(self.cookie)

    @filter.command("搜视频")
    async def search_video_handle(self, event: AstrMessageEvent):
        """搜索视频"""

        # 获取用户输入的视频名称
        video_name = event.message_str.replace("搜视频", "")

        # 获取搜索结果
        video_list = await self.api.search_video(video_name)
        if not video_list:
            yield event.plain_result("没有找到相关视频")
            return

        # 展示搜索结果
        video_infos = self.api.display_video_info(video_list)
        image = await self.text_to_image(video_infos)
        yield event.image_result(image)

        # 等待用户选择歌曲
        @session_waiter(timeout=60, record_history_chains=False) # type: ignore
        async def empty_mention_waiter(
            controller: SessionController, event: AstrMessageEvent
        ):
            # 获取用户输入的索引
            choice_index = event.message_str
            if (
                not choice_index.isdigit()
                or int(choice_index) < 1
                or int(choice_index) > len(video_list)
            ):
                return
            await event.send(event.plain_result(f"正在下载视频【{choice_index}】..."))
            logger.info(f"正在下载视频: {video_list[int(choice_index) - 1].get('title')}")
            controller.stop()

            # 获取视频信息
            video_dict = video_list[int(choice_index) - 1]
            bvid: str = video_dict.get("bvid", "")
            duration_str: str = video_dict.get("duration", "0")

            # 视频时长是否超过最大时长时发链接，否则发送视频
            duration = self.convert_duration_to_seconds(duration_str)
            if duration > self.max_duration:
                video_url = f"https://www.bilibili.com/video/{bvid}"
                await event.send(event.plain_result(f"视频有点长：{video_url}"))
            else:
                data_path = await self.api.download_video(bvid)
                if data_path:
                    await self.send_video(event, data_path)

        try:
            await empty_mention_waiter(event)  # type: ignore
        except TimeoutError as _:
            yield event.plain_result("操作超时！")
        except Exception as e:
            logger.error("搜索视频发生错误" + str(e))
        finally:
            event.stop_event()

    async def send_video(self, event: AstrMessageEvent, data_path: str):
        """发送视频"""
        try:
            # 检测文件大小(如果视频大于 100 MB 自动转换为群文件)
            file_size_mb = int(os.path.getsize(data_path) / (1024 * 1024))
            if file_size_mb > 100:
                if event.get_platform_name() == "aiocqhttp":
                    from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
                        AiocqhttpMessageEvent,
                    )

                    assert isinstance(event, AiocqhttpMessageEvent)
                    client = event.bot
                    group_id = event.get_group_id()
                    name = data_path.split("/")[-1]
                    if group_id:
                        # 上传群文件
                        await client.upload_group_file(
                            group_id=group_id, file=data_path, name=name
                        )
                    else:
                        # 上传私聊文件
                        await client.upload_private_file(
                            user_id=int(event.get_sender_id()),
                            file=data_path,
                            name=name,
                        )
                    return
            await event.send(event.chain_result([Video.fromFileSystem(data_path)]))
        except Exception as e:
            logger.error(f"解析发送出现错误，具体为\n{e}")
        finally:
            # 删除临时文件
            if os.path.exists(data_path):
                os.unlink(data_path)

    @staticmethod
    def convert_duration_to_seconds(duration_str):
        """将视频时长从 'HH:MM:SS'、'MM:SS' 或 'SS' 格式转换为秒"""
        if not duration_str:
            return 0
        seconds = 0
        parts = duration_str.split(":")
        for i, part in enumerate(reversed(parts)):
            if i == 0:
                seconds += int(part)
            elif i == 1:
                seconds += int(part) * 60
            elif i == 2:
                seconds += int(part) * 3600
        return seconds

    def _remove_files(self, file_paths: list[str]) -> dict[str, str]:
        """
        根据路径删除文件

        Parameters:
        *file_paths (str): 要删除的一个或多个文件路径

        Returns:
        dict: 一个以文件路径为键、删除状态为值的字典
        """
        results = {}

        for file_path in file_paths:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    results[file_path] = "remove"
                except Exception as e:
                    results[file_path] = f"error: {e}"
            else:
                results[file_path] = "don't exist"

        return results


