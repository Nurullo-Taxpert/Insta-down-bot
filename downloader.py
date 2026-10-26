import os
import uuid
import subprocess
import yt_dlp
from pathlib import Path
from config import DOWNLOAD_DIR, COOKIES_FILE, MAX_FILE_SIZE

try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_PATH = None


class MediaDownloader:
    @staticmethod
    def _get_ydl_opts(output_template: str, is_youtube: bool = False) -> dict:
        if is_youtube:
            # YouTube uchun 50 MB gacha bo'lgan eng yaxshi formatni tanlaymiz
            fmt = (
                'best[filesize<50M][ext=mp4]/'
                'bestvideo[filesize<40M][ext=mp4]+bestaudio[ext=m4a]/'
                'best[ext=mp4]/'
                'best'
            )
        else:
            # Instagram uchun
            fmt = 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best'

        opts = {
            'outtmpl': output_template,
            'format': fmt,
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'socket_timeout': 35,
            'http_headers': {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0.0.0 Safari/537.36'
                ),
                'Accept-Language': 'en-US,en;q=0.9',
            }
        }

        # FFmpeg manzilini o'rnatamiz
        if FFMPEG_PATH:
            opts['ffmpeg_location'] = FFMPEG_PATH

        # Cookies fayli mavjud bo'lsa ulaymiz
        if COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0:
            opts['cookiefile'] = str(COOKIES_FILE)

        return opts

    @classmethod
    def download(cls, url: str) -> dict:
        """
        Instagram yoki YouTube havolasidan videoni yuklab oladi.
        """
        is_youtube = ("youtube.com" in url) or ("youtu.be" in url)
        platform_name = "YouTube" if is_youtube else "Instagram"

        unique_id = str(uuid.uuid4())[:8]
        output_template = str(DOWNLOAD_DIR / f"media_{unique_id}_%(id)s.%(ext)s")
        ydl_opts = cls._get_ydl_opts(output_template, is_youtube=is_youtube)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    return {
                        "success": False,
                        "error": "Video ma'lumotlarini olib bo'lmadi. Havolani tekshiring."
                    }

                # Agar karusel yoki playlist bo'lsa
                if 'entries' in info:
                    entries = [e for e in info['entries'] if e]
                    if entries:
                        info = entries[0]
                    else:
                        return {"success": False, "error": "Video topilmadi."}

                filename = ydl.prepare_filename(info)
                file_path = Path(filename)

                # Format mp4 bo'lishini ta'minlash
                if not file_path.exists():
                    mp4_path = file_path.with_suffix(".mp4")
                    if mp4_path.exists():
                        file_path = mp4_path
                    else:
                        matched = list(DOWNLOAD_DIR.glob(f"media_{unique_id}_*"))
                        if matched:
                            file_path = matched[0]
                        else:
                            return {
                                "success": False,
                                "error": "Yuklangan video fayli diskda topilmadi."
                            }

                # Hajmini tekshirish (Telegram Bot API 50 MB limiti)
                file_size = file_path.stat().st_size
                if file_size > MAX_FILE_SIZE:
                    file_path.unlink(missing_ok=True)
                    return {
                        "success": False,
                        "error": (
                            f"Video hajmi juda katta ({file_size / (1024*1024):.1f} MB).\n"
                            "Telegram bot faqat 50 MB gacha bo'lgan videolarni yubora oladi."
                        )
                    }

                return {
                    "success": True,
                    "platform": platform_name,
                    "file_path": str(file_path),
                    "title": info.get("title") or info.get("description") or f"{platform_name} Video",
                    "uploader": info.get("uploader") or info.get("channel") or platform_name,
                    "duration": int(info.get("duration") or 0),
                    "width": info.get("width"),
                    "height": info.get("height"),
                    "filesize": file_size
                }

        except yt_dlp.utils.DownloadError as e:
            error_text = str(e).lower()
            if "login required" in error_text or "checkpoint" in error_text or "sign in" in error_text:
                msg = (
                    f"Ushbu {platform_name} videosini yuklab olish uchun kirish talab etiladi "
                    "(yopiq yoki cheklangan video)."
                )
            elif "not found" in error_text or "404" in error_text:
                msg = "Video topilmadi yoki muallif tomonidan o'chirilgan."
            elif "private" in error_text:
                msg = "Ushbu video yopiq (private) hisobdan olingan."
            else:
                msg = f"Yuklab olishda xatolik yuz berdi: {str(e)[:150]}"
            return {"success": False, "error": msg}

        except Exception as e:
            return {"success": False, "error": f"Kutilmagan xatolik: {str(e)[:150]}"}

    @staticmethod
    def convert_to_round_video(input_path: str, output_path: str, max_duration: int = 60) -> dict:
        """
        Istalgan to'rtburchak videoni Telegram Dumaloq Video (Video Note) formatiga aylantiradi:
        - 1:1 markaziy kvadrat qirqish (crop)
        - 480x480 o'lcham
        - H.264 video va AAC audio
        - Maksimal 60 soniya (Telegram video_note standarti)
        """
        if not FFMPEG_PATH:
            return {
                "success": False,
                "error": "FFmpeg topilmadi. Dumaloq videoga aylantirib bo'lmaydi."
            }

        try:
            cmd = [
                FFMPEG_PATH,
                "-y",
                "-i", str(input_path),
                "-t", str(max_duration),
                "-vf", "crop=min(iw\\,ih):min(iw\\,ih),scale=480:480,setsar=1",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "24",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_path)
            ]

            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            if process.returncode != 0:
                return {
                    "success": False,
                    "error": f"FFmpeg xatoligi: {process.stderr[-200:]}"
                }

            out_p = Path(output_path)
            if not out_p.exists() or out_p.stat().st_size == 0:
                return {
                    "success": False,
                    "error": "Dumaloq video fayli yaratilmadi."
                }

            return {
                "success": True,
                "file_path": str(out_p),
                "filesize": out_p.stat().st_size
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Aylantirishda xatolik yuz berdi: {str(e)[:150]}"
            }
