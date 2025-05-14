import os
import time
from typing import Callable, List, Dict
import aiofiles
import httpx
import asyncio
import platform
import subprocess
from bilibili_api import video, Credential
from bilibili_api.video import VideoDownloadURLDataDetecter
from bs4 import BeautifulSoup
from astrbot import logger

class VideoAPI():
    """
    视频API类
    """
    # 构造函数
    def __init__(self, cookie: str):
        self.cookie = cookie

        self.BILIBILI_SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"

        self.BILIBILI_HEADER2 = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36",
            "Referer": "https://www.bilibili.com",
            "Origin": "https://www.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Cookie": self.cookie,
        }


        self.BILIBILI_HEADER = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 "
            "Safari/537.36",
            "referer": "https://www.bilibili.com",
        }


        self.COMMON_HEADER = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 "
            "UBrowser/6.2.4098.3 Safari/537.36"
        }

    async def search_video(self, keyword: str) -> list[dict] | None:
        """
        搜索视频
        """
        params = {"search_type": "video", "keyword": keyword, "page": 1}
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    self.BILIBILI_SEARCH_API, params=params, headers=self.BILIBILI_HEADER2
                )
                response.raise_for_status()
                data = response.json()

                if data["code"] == 0:
                    video_list = data["data"].get("result", [])
                    return video_list

            except Exception as e:
                logger.error(f"发生错误: {e}")
                return []

    def display_video_info(self, video_list: list[dict]) -> str:
        """
        展示视频信息
        """
        video_infos = []
        for index, video_ in enumerate(video_list):
            title = BeautifulSoup(video_.get("title", "无标题"), "html.parser").get_text()
            author = video_.get("author", "未知作者")
            duration = video_.get("duration", "未知时长")
            play_count = video_.get("play", "未知播放量")
            favorites = video_.get("favorites", "未知收藏量")
            likes = video_.get("like", "未知点赞数")
            description = BeautifulSoup(
                video_.get("description", "无简介"), "html.parser"
            ).get_text()
            tags = video_.get("tag", "无标签")
            pubdate = time.strftime("%Y-%m-%d", time.localtime(video_.get("pubdate", 0)))

            # 使用 Markdown 格式生成单个视频的信息
            info_str = (
                f"### {index + 1}. {title}\n"
                f"- **作者**: {author} | **日期**: {pubdate}\n"
                f"- **时长**: {duration} | **播放量**: {play_count} | **点赞数**: {likes} | **收藏量**: {favorites}\n"
                f"- **简介**: {description}\n"
                f"- **标签**: {tags}\n"
            )
            video_infos.append(info_str)

        # 将所有视频信息拼接为一个 Markdown 格式的字符串
        return "\n\n".join(video_infos)

    async def download_video(self, video_id: str) -> str | None:
        """下载视频"""

        # 获取视频信息
        v = video.Video(video_id, credential=Credential(sessdata=""))
        # 获取视频流和音频流下载链接
        download_url_data = await v.get_download_url(page_index=0)
        detector = VideoDownloadURLDataDetecter(download_url_data)
        streams = detector.detect_best_streams()
        video_url, audio_url = streams[0].url, streams[1].url

        # 下载视频和音频并合并
        path = os.getcwd() + "/" + video_id
        try:
            await asyncio.gather(
                self._download_b_file(video_url, f"{path}-video.m4s", logger.info),
                self._download_b_file(audio_url, f"{path}-audio.m4s", logger.info),
            )
            await self._merge_file_to_mp4(
                f"{video_id}-video.m4s", f"{video_id}-audio.m4s", f"{path}-res.mp4"
            )
            return f"{path}-res.mp4"
        except Exception as e:
            logger.error(f"视频/音频下载失败，具体为\n{e}")
            return
        finally:
            remove_res = self._remove_files(
                [f"{video_id}-video.m4s", f"{video_id}-audio.m4s"]
            )
            logger.info(remove_res)

    async def _download_b_file(self, url: str, full_file_name: str, progress_callback: Callable[[str], None]):
        """
        下载视频文件和音频文件
        :param url:
        :param full_file_name:
        :param progress_callback:
        :return:
        """
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", url, headers=self.BILIBILI_HEADER) as resp:
                current_len = 0
                total_len = int(resp.headers.get("content-length", 0))
                async with aiofiles.open(full_file_name, "wb") as f:
                    async for chunk in resp.aiter_bytes():
                        current_len += len(chunk)
                        await f.write(chunk)
                        progress_callback(f"下载进度：{round(current_len / total_len, 3)}")


    async def _merge_file_to_mp4(
        self,
        v_full_file_name: str,
        a_full_file_name: str,
        output_file_name: str,
        log_output: bool = False,
    ) -> None:
        """
        合并视频文件和音频文件
        :param v_full_file_name: 视频文件路径
        :param a_full_file_name: 音频文件路径
        :param output_file_name: 输出文件路径
        :param log_output: 是否显示 ffmpeg 输出日志，默认忽略
        :return:
        """
        print(f"正在合并：{output_file_name}")

        # 构建 ffmpeg 命令
        command = f'ffmpeg -y -i "{v_full_file_name}" -i "{a_full_file_name}" -c copy "{output_file_name}"'
        stdout = None if log_output else subprocess.DEVNULL
        stderr = None if log_output else subprocess.DEVNULL

        if platform.system() == "Windows":
            # Windows 下使用 run_in_executor
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: subprocess.call(command, shell=True, stdout=stdout, stderr=stderr),  # noqa: ASYNC221
            )
        else:
            # 其他平台使用 create_subprocess_shell
            process = await asyncio.create_subprocess_shell(
                command, shell=True, stdout=stdout, stderr=stderr
            )
            await process.communicate()

    def _remove_files(self, file_paths: List[str]) -> Dict[str, str]:
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
