"""
百度网盘 API 封装：使用 BDUSS/BDUSS_BFESS Cookie 实现文件列表、分享解析、下载链接获取
所有接口使用百度网盘内部 Web API（支持 Cookie 认证），不需要 access_token。
"""
import re
import json
import time
import hashlib
import requests
from urllib.parse import unquote, quote_plus
from .logger import get_logger

logger = get_logger()


class BaiduPanAPI:
    """百度网盘 API 接口（Cookie 认证）"""

    BASE = "https://pan.baidu.com"

    UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(self, bduss: str = "", bduss_bfess: str = ""):
        self.bduss = bduss.strip()
        self.bduss_bfess = bduss_bfess.strip()
        self.bdstoken = ""
        self.session = requests.Session()
        self._setup_session()

    # ─── 会话设置 ──────────────────────────────────────────────

    def _setup_session(self):
        if self.bduss:
            self.session.cookies.set('BDUSS', self.bduss, domain='.baidu.com', path='/')
        if self.bduss_bfess:
            self.session.cookies.set('BDUSS_BFESS', self.bduss_bfess, domain='.baidu.com', path='/')
        self.session.headers.update({
            "User-Agent": self.UA,
            "Referer": "https://pan.baidu.com/disk/home",
            "Accept": "application/json, text/plain, */*",
        })

    def update_credentials(self, bduss: str, bduss_bfess: str):
        self.bduss = bduss.strip()
        self.bduss_bfess = bduss_bfess.strip()
        self.bdstoken = ""
        self.session.cookies.clear()
        self._setup_session()

    def update_credentials_from_cookie_string(self, cookie_str: str):
        """从完整的Cookie字符串设置所有Cookie"""
        self.bdstoken = ""
        self.session.cookies.clear()
        self.session.headers.update({
            "User-Agent": self.UA,
            "Referer": "https://pan.baidu.com/disk/home",
            "Accept": "application/json, text/plain, */*",
        })
        for item in re.split(r';\s*', cookie_str.strip().rstrip(';')):
            item = item.strip()
            if '=' in item:
                key, val = item.split('=', 1)
                key = key.strip()
                val = val.strip()
                if key in ('BDUSS', 'BDUSS_BFESS'):
                    self.session.cookies.set(key, val, domain='.baidu.com', path='/')
                    if key == 'BDUSS':
                        self.bduss = val
                    else:
                        self.bduss_bfess = val
                elif key:
                    self.session.cookies.set(key, val, domain='.baidu.com', path='/')

    def _fetch_bdstoken(self):
        """从网盘首页提取 bdstoken（部分 API 需要）"""
        if self.bdstoken:
            return
        try:
            resp = self.session.get(f"{self.BASE}/disk/home", timeout=15)
            m = re.search(r'"bdstoken"\s*:\s*"([a-f0-9]{32})"', resp.text)
            if m:
                self.bdstoken = m.group(1)
        except Exception:
            pass

    # ─── 用户信息 ──────────────────────────────────────────────

    def get_user_info(self) -> dict:
        """获取当前登录用户信息，通过访问网盘首页解析"""
        try:
            resp = self.session.get(f"{self.BASE}/disk/home", timeout=15,
                                     allow_redirects=True)
            text = resp.text
            final_url = resp.url

            # 检查是否被重定向到登录页
            if "/login" in final_url or "/passport/" in final_url:
                bduss_len = len(self.bduss) if self.bduss else 0
                return {"errno": -6,
                        "errmsg": f"BDUSS 无效或已过期（长度={bduss_len}）。"
                                  f"请在浏览器 F12 → Application → Cookies 中"
                                  f"重新复制 BDUSS 的值（不要复制整行）"}

            # 检查页面内容是否是登录页
            if "login-btn" in text and "netdisk" not in text.lower():
                return {"errno": -6,
                        "errmsg": "BDUSS 无效或已过期，请重新从浏览器获取"}

            # 提取用户名
            username = ""
            patterns = [
                r'"username"\s*:\s*"([^"]+)"',
                r'"loginUserName"\s*:\s*"([^"]+)"',
                r'"UNAME"\s*:\s*"([^"]+)"',
                r'"user_name"\s*:\s*"([^"]+)"',
                r'"show_name"\s*:\s*"([^"]+)"',
                r'data-username="([^"]+)"',
            ]
            for pat in patterns:
                m = re.search(pat, text)
                if m:
                    username = m.group(1)
                    break

            # 提取 bdstoken
            m = re.search(r'"bdstoken"\s*:\s*"([a-f0-9]{32})"', text)
            if m:
                self.bdstoken = m.group(1)

            # 如果没找到用户名但页面加载正常（已登录）
            if not username and ("netdisk" in text.lower() or "disk" in resp.url):
                username = "用户"

            if username:
                return {"errno": 0, "username": username}

            return {"errno": -6, "errmsg": "无法获取用户信息"}

        except Exception as e:
            return {"errno": -1, "errmsg": str(e)}

    def is_logged_in(self) -> bool:
        try:
            info = self.get_user_info()
            return info.get("errno", -1) == 0
        except Exception:
            return False

    # ─── 文件列表 ──────────────────────────────────────────────

    def list_files(self, dir_path: str = "/", page: int = 1, num: int = 100,
                   order: str = "name", desc: int = 0) -> dict:
        """列出指定目录的文件/文件夹"""
        self._fetch_bdstoken()
        url = f"{self.BASE}/api/list"
        params = {
            "dir": dir_path,
            "page": page,
            "num": num,
            "order": order,
            "desc": desc,
            "clienttype": 0,
            "web": 1,
            "channel": "chunlei",
        }
        if self.bdstoken:
            params["bdstoken"] = self.bdstoken
        resp = self.session.get(url, params=params, timeout=15)
        return resp.json()

    # ─── 文件元信息 / 下载链接 ─────────────────────────────────

    def get_file_metas(self, fs_ids: list) -> dict:
        """获取文件信息（含 dlink 下载链接）"""
        self._fetch_bdstoken()
        url = f"{self.BASE}/api/filemetas"
        params = {
            "fsids": json.dumps(fs_ids),
            "dlink": 1,
            "channel": "chunlei",
            "web": 1,
            "clienttype": 0,
        }
        if self.bdstoken:
            params["bdstoken"] = self.bdstoken
        resp = self.session.get(url, params=params, timeout=15)
        return resp.json()

    def get_download_link(self, fs_id: int) -> str | None:
        """获取单个文件的真实下载链接"""
        data = self.get_file_metas([fs_id])
        if data.get("errno") != 0:
            return None
        items = data.get("list", data.get("info", []))
        if not items:
            return None
        dlink = items[0].get("dlink", "")
        return dlink if dlink else None

    def get_real_download_url(self, dlink: str) -> str:
        """通过 dlink 获取 302 跳转后的真实下载地址"""
        headers = {"User-Agent": self.UA}
        resp = self.session.head(dlink, headers=headers, allow_redirects=False, timeout=15)
        return resp.headers.get("Location", dlink)

    # ─── 分享链接解析 ──────────────────────────────────────────

    @staticmethod
    def parse_share_url(url: str) -> dict | None:
        """
        从分享链接中提取 surl
        支持格式：
          - https://pan.baidu.com/s/1xxxxx
          - https://pan.baidu.com/s/1xxxxx?pwd=xxxx
          - https://pan.baidu.com/share/init?surl=xxxxx
        """
        url = url.strip()
        m = re.search(r'pan\.baidu\.com/s/1([A-Za-z0-9_-]+)', url)
        if m:
            return {"surl": m.group(1)}
        m = re.search(r'surl=([A-Za-z0-9_-]+)', url)
        if m:
            return {"surl": m.group(1)}
        return None

    def verify_share(self, surl: str, pwd: str = "") -> dict:
        """验证分享链接提取码"""
        url = f"{self.BASE}/share/verify"
        params = {"surl": surl}
        data = {"pwd": pwd, "vcode": "", "vcode_str": ""}
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"https://pan.baidu.com/share/init?surl={surl}",
        }
        resp = self.session.post(url, params=params, data=data,
                                  headers=headers, timeout=15)
        return resp.json()

    def get_share_page_info(self, surl: str) -> dict:
        """从分享页面提取 shareid, uk, file_list 等"""
        url = f"{self.BASE}/s/1{surl}"
        resp = self.session.get(url, timeout=15)
        text = resp.text
        info = {}

        patterns = {
            "shareid": [r'"shareid"\s*:\s*["\']?(\d+)', r'shareid\s*:\s*"(\d+)"'],
            "uk": [r'"share_uk"\s*:\s*"(\d+)"', r'share_uk\s*:\s*"(\d+)"',
                   r'"uk"\s*:\s*["\']?(\d+)'],
        }
        for key, pats in patterns.items():
            for pat in pats:
                m = re.search(pat, text)
                if m:
                    info[key] = m.group(1)
                    break

        # 从 locals.mset 提取文件列表（最可靠的方式）
        m = re.search(r'locals\.mset\(({.*?})\)', text, re.DOTALL)
        if m:
            try:
                mset = json.loads(m.group(1))
                file_list = mset.get("file_list", [])
                if isinstance(file_list, dict):
                    file_list = file_list.get("list", [])
                if file_list:
                    info["file_list"] = file_list
            except Exception:
                pass

        # 备用：直接搜索 file_list JSON 数组
        if "file_list" not in info:
            m = re.search(r'"file_list"\s*:\s*(\[.*?\])', text, re.DOTALL)
            if m:
                try:
                    file_list = json.loads(m.group(1))
                    if file_list:
                        info["file_list"] = file_list
                except Exception:
                    pass

        return info

    def list_share_files(self, surl: str, pwd: str = "",
                         dir_path: str = "/", page: int = 1) -> dict:
        """列出分享链接中的文件列表"""
        randsk = ""
        if pwd:
            verify = self.verify_share(surl, pwd)
            if verify.get("errno") != 0:
                return verify
            randsk = verify.get("randsk", "")
            if randsk:
                self.session.cookies.set("BDCLND", randsk)
        else:
            for cookie in self.session.cookies:
                if cookie.name == "BDCLND":
                    randsk = cookie.value
                    break

        page_info = self.get_share_page_info(surl)

        # 保存 shareid 和 uk 供后续使用
        shareid = page_info.get("shareid", "")
        uk = page_info.get("uk", "")

        if dir_path == "/" and "file_list" in page_info:
            return {
                "errno": 0,
                "list": page_info["file_list"],
                "shareid": shareid,
                "uk": uk,
                "randsk": randsk,
            }

        if not shareid or not uk:
            return {"errno": -1, "errmsg": "无法从分享页面提取信息，链接可能无效或已过期"}

        url = f"{self.BASE}/share/list"
        params = {
            "shareid": shareid,
            "uk": uk,
            "dir": dir_path,
            "page": page,
            "num": 100,
            "order": "name",
            "channel": "chunlei",
            "web": 1,
            "clienttype": 0,
        }
        resp = self.session.get(url, params=params, timeout=15)
        data = resp.json()
        data["shareid"] = shareid
        data["uk"] = uk
        data["randsk"] = randsk
        return data

    def list_share_dir(self, shareid: str, uk: str, dir_path: str,
                       page: int = 1) -> dict:
        """列出分享链接中子目录的内容"""
        url = f"{self.BASE}/share/list"
        params = {
            "shareid": shareid,
            "uk": uk,
            "dir": dir_path,
            "page": page,
            "num": 100,
            "order": "name",
            "channel": "chunlei",
            "web": 1,
            "clienttype": 0,
        }
        resp = self.session.get(url, params=params, timeout=15)
        return resp.json()

    def transfer_share_files(self, surl: str, from_fs_ids: list,
                              to_path: str = "/", randsk: str = "") -> dict:
        """转存分享文件到自己的网盘。

        百度的分享转存接口对 sekey、BDCLND、Referer 和 bdstoken 很敏感。
        这里按 macOS 端相同策略尝试几种等价请求，避免 errno=2 只能靠用户反复点击。
        """
        self._fetch_bdstoken()
        page_info = self.get_share_page_info(surl)

        shareid = page_info.get("shareid")
        uk = page_info.get("uk")

        if not shareid or not uk:
            return {"errno": -1, "errmsg": "无法提取 shareid/uk"}

        decoded_randsk = unquote(randsk or "")
        original_randsk = randsk or decoded_randsk
        active_bdclnd = original_randsk or decoded_randsk
        if active_bdclnd:
            self.session.cookies.set("BDCLND", active_bdclnd, domain=".baidu.com", path="/")

        url = f"{self.BASE}/share/transfer"
        base_params = {
            "shareid": shareid,
            "from": uk,
            "channel": "chunlei",
            "web": 1,
            "clienttype": 0,
        }

        compact_fsidlist = json.dumps(from_fs_ids, separators=(",", ":"))
        spaced_fsidlist = json.dumps(from_fs_ids)
        share_referer = f"https://pan.baidu.com/share/init?surl={surl}"
        page_referer = f"https://pan.baidu.com/s/1{surl}"
        attempts = [
            ("legacy", decoded_randsk, active_bdclnd, compact_fsidlist, None, True),
            ("share_referer", decoded_randsk, active_bdclnd, compact_fsidlist, share_referer, True),
            ("page_referer", decoded_randsk, active_bdclnd, compact_fsidlist, page_referer, True),
            ("json_spaces", decoded_randsk, active_bdclnd, spaced_fsidlist, None, True),
            ("no_bdstoken", decoded_randsk, active_bdclnd, compact_fsidlist, None, False),
            ("no_sekey", "", active_bdclnd, compact_fsidlist, None, True),
        ]
        if original_randsk and original_randsk != decoded_randsk:
            attempts.insert(
                1,
                ("original_sekey", original_randsk, active_bdclnd, compact_fsidlist, None, True),
            )
            attempts.append(
                ("decoded_cookie", decoded_randsk, decoded_randsk, compact_fsidlist, None, True)
            )

        seen = set()
        last_result = None
        for name, sekey, bdclnd, fsidlist, referer, include_bdstoken in attempts:
            dedupe_key = (sekey, bdclnd, fsidlist, referer, include_bdstoken)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            params = dict(base_params)
            if include_bdstoken and self.bdstoken:
                params["bdstoken"] = self.bdstoken
            if sekey:
                params["sekey"] = sekey

            headers = {
                "Origin": self.BASE,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": referer or "https://pan.baidu.com/disk/home",
            }
            if bdclnd:
                headers["Cookie"] = self._cookie_header(overriding_bdclnd=bdclnd)

            data = {"fsidlist": fsidlist, "path": to_path}
            try:
                resp = self.session.post(
                    url, params=params, data=data, headers=headers, timeout=15
                )
                result = resp.json()
            except Exception as e:
                logger.debug(f" transfer_share_files attempt={name} failed: {e}")
                last_result = {"errno": -1, "errmsg": str(e)}
                continue

            errno = result.get("errno")
            logger.debug(
                f" transfer_share_files attempt={name} errno={errno} "
                f"fsid_count={len(from_fs_ids)} to_path={to_path}"
            )
            if errno == 0:
                return result
            last_result = result

        return last_result or {"errno": -1, "errmsg": "转存请求失败"}

    def _cookie_header(self, overriding_bdclnd: str = "") -> str:
        parts = []
        bdclnd_seen = False
        for cookie in self.session.cookies:
            if cookie.name == "BDCLND":
                bdclnd_seen = True
                if overriding_bdclnd:
                    parts.append(f"BDCLND={overriding_bdclnd}")
                else:
                    parts.append(f"{cookie.name}={cookie.value}")
            else:
                parts.append(f"{cookie.name}={cookie.value}")
        if overriding_bdclnd and not bdclnd_seen:
            parts.append(f"BDCLND={overriding_bdclnd}")
        return "; ".join(parts)

    # ─── locatedownload（高速下载） ─────────────────────────────

    PCS_UA = "softxm;netdisk"

    def _get_bduss(self) -> str:
        for c in self.session.cookies:
            if c.name == "BDUSS":
                return c.value
        return self.bduss

    def _get_user_id(self) -> str:
        if not hasattr(self, '_cached_uid') or not self._cached_uid:
            try:
                resp = self.session.get(
                    f"{self.BASE}/rest/2.0/xpan/nas?method=uinfo",
                    headers={"User-Agent": self.UA}, timeout=10,
                )
                self._cached_uid = str(resp.json().get("uk", ""))
            except Exception:
                self._cached_uid = ""
        return self._cached_uid

    def get_locate_download_url(self, path: str, app_id: str = "250528") -> str:
        """使用 locatedownload 方法获取高速下载链接（需要客户端签名）"""
        import urllib.request

        bduss = self._get_bduss()
        if not bduss:
            return ""

        uid = self._get_user_id()
        enc = hashlib.sha1(bduss.encode()).hexdigest()
        devuid = hashlib.md5(bduss.encode()).hexdigest().upper() + "|0"
        timestamp = str(int(time.time()))
        rand = hashlib.sha1(
            (enc + uid + "ebrcUYiuxaZv2XGu7KIYKxUrqfnOfpDF" + timestamp + devuid).encode()
        ).hexdigest()

        params = {
            "apn_id": "1_0",
            "app_id": app_id,
            "channel": "0",
            "check_blue": "1",
            "clienttype": "17",
            "es": "1",
            "esl": "1",
            "freeisp": "0",
            "method": "locatedownload",
            "path": quote_plus(path),
            "queryfree": "0",
            "use": "0",
            "ver": "4.0",
            "time": timestamp,
            "rand": rand,
            "devuid": devuid,
            "cuid": devuid,
        }

        url = "https://pcs.baidu.com/rest/2.0/pcs/file?" + "&".join(
            f"{k}={v}" for k, v in params.items()
        )

        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": self.PCS_UA,
                "Cookie": f"BDUSS={bduss};",
            }, method="GET")
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read())

            if data.get("host") == "issuecdn.baidupcs.com":
                logger.debug(f" locatedownload: file blocked (issuecdn)")
                return ""

            if data.get("urls"):
                dl_url = data["urls"][0]["url"]
                logger.debug(f" locatedownload ok (app_id={app_id}): "
                      f"{dl_url[:100]}...")
                return dl_url
        except Exception as e:
            logger.debug(f" locatedownload failed (app_id={app_id}): {e}")

        return ""

    def delete_files(self, file_paths: list, onnest: str = "fail") -> dict:
        """删除网盘中的文件"""
        self._fetch_bdstoken()
        url = f"{self.BASE}/api/filemanager"
        params = {
            "opera": "delete",
            "async": 2,
            "onnest": onnest,
            "channel": "chunlei",
            "web": 1,
            "clienttype": 0,
        }
        if self.bdstoken:
            params["bdstoken"] = self.bdstoken
        data = {"filelist": json.dumps(file_paths)}
        resp = self.session.post(url, params=params, data=data, timeout=15)
        return resp.json()

    def create_dir(self, path: str) -> dict:
        """在网盘中创建目录"""
        self._fetch_bdstoken()
        url = f"{self.BASE}/api/create"
        params = {
            "a": "commit",
            "channel": "chunlei",
            "web": 1,
            "clienttype": 0,
        }
        if self.bdstoken:
            params["bdstoken"] = self.bdstoken
        data = {"path": path, "isdir": 1, "block_list": "[]"}
        resp = self.session.post(url, params=params, data=data, timeout=15)
        return resp.json()

    # ─── 搜索 ─────────────────────────────────────────────────

    def search_files(self, keyword: str, dir_path: str = "/",
                     page: int = 1, num: int = 100) -> dict:
        """搜索网盘文件"""
        self._fetch_bdstoken()
        url = f"{self.BASE}/api/search"
        params = {
            "key": keyword,
            "dir": dir_path,
            "page": page,
            "num": num,
            "recursion": 1,
            "channel": "chunlei",
            "web": 1,
            "clienttype": 0,
        }
        if self.bdstoken:
            params["bdstoken"] = self.bdstoken
        resp = self.session.get(url, params=params, timeout=15)
        return resp.json()

    # ─── 用量信息 ──────────────────────────────────────────────

    def get_quota(self) -> dict:
        """获取网盘容量信息"""
        url = f"{self.BASE}/api/quota"
        params = {"checkexpire": 1, "checkfree": 1}
        resp = self.session.get(url, params=params, timeout=15)
        return resp.json()
