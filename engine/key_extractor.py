import os
import sys


class KeyExtractionError(Exception):
    """Raised when key extraction fails for a specific path."""
    pass


def _is_valid_key(s) -> bool:
    return isinstance(s, str) and len(s) == 64 and all(c in '0123456789abcdefABCDEF' for c in s)


def _verify_key_on_shard(key: str, shard_path: str) -> bool:
    """Verify a key by attempting to decrypt a test shard with pywxdump."""
    import os as _os, tempfile
    try:
        import pywxdump
        tmp = tempfile.mktemp(suffix=".db")
        ok, _ = pywxdump.decrypt(key, shard_path, tmp)
        if ok and _os.path.isfile(tmp):
            # Quick SQLite validation
            import sqlite3
            try:
                conn = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
                conn.execute("SELECT 1")
                conn.close()
                _os.unlink(tmp)
                return True
            except sqlite3.Error:
                pass
        # Cleanup
        for p in [tmp, tmp + "-journal", tmp + "-wal"]:
            try:
                _os.unlink(p)
            except OSError:
                pass
    except Exception:
        pass
    return False


class KeyExtractor:
    """Extract WeChat database AES key via PyWxDump (primary) -> pymem (fallback)."""

    def __init__(self):
        self._missing_deps: set[str] = set()
        self._debug: list[str] = []
        self._key_wxid: str | None = None

    @property
    def missing_deps(self) -> set[str]:
        return set(self._missing_deps)

    @property
    def key_wxid(self) -> str | None:
        """The wxid that the extracted key belongs to (from pywxdump)."""
        return self._key_wxid

    @property
    def debug_log(self) -> str:
        return "\n".join(self._debug)

    def _log(self, msg: str):
        self._debug.append(msg)

    def install_missing(self) -> tuple[bool, str]:
        deps = list(self._missing_deps)
        if not deps:
            return (True, "所有依赖已就绪")
        try:
            import subprocess
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install"] + deps,
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                self._missing_deps.clear()
                return (True, f"安装成功: {' '.join(deps)}")
            return (False, result.stderr.strip()[:500] or result.stdout.strip()[:500])
        except Exception as e:
            return (False, str(e))

    def extract_key(self) -> str | None:
        """Return 32-byte hex key string (64 chars), or None if all paths fail."""
        self._debug = []
        self._missing_deps = set()

        # -- Cached key path --
        from config.settings import load_config
        cached = load_config().get("cached_wx_key", "")
        if cached and _is_valid_key(cached):
            test_shard = self._find_test_shard()
            if test_shard:
                self._log("[0/3] 尝试缓存密钥...")
                if _verify_key_on_shard(cached, test_shard):
                    self._log("[成功] 缓存密钥有效")
                    return cached
                self._log("[跳过] 缓存密钥无效")

        # -- PyWxDump path --
        self._log("[1/3] 尝试 PyWxDump 路径...")
        try:
            key = self._try_pywxdump()
            self._log("[成功] PyWxDump 获取密钥成功")
            return key
        except ImportError:
            self._log("[失败] pywxdump 未安装 (pip install pywxdump)")
            self._missing_deps.add("pywxdump")
        except KeyExtractionError as e:
            self._log(f"[失败] PyWxDump: {e}")

        # -- pymem path --
        self._log("[2/3] 尝试 pymem 内存扫描路径...")
        try:
            key = self._try_pymem()
            self._log("[成功] pymem 内存扫描获取密钥成功")
            return key
        except ImportError:
            self._log("[失败] pymem 未安装 (pip install pymem)")
            self._missing_deps.add("pymem")
        except KeyExtractionError as e:
            self._log(f"[失败] pymem: {e}")

        self._log("[结果] 所有密钥提取路径均失败")
        return None

    def _try_pywxdump(self) -> str:
        try:
            import pywxdump
        except ImportError:
            raise ImportError("pywxdump not installed")

        self._log("  pywxdump 已安装")

        try:
            from pywxdump.wx_core.wx_info import get_info_details
        except ImportError:
            self._log("  wx_info module not available")
            raise KeyExtractionError("PyWxDump: wx_info module not found")

        # Only try the main WeChat process (WeChat.exe / Weixin.exe).
        import psutil
        main_pids = []
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                name = proc.info['name'].lower()
                if name in ('wechat.exe', 'weixin.exe', 'wechatstore.exe'):
                    main_pids.append(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not main_pids:
            self._log("  未找到微信主进程 (WeChat.exe / Weixin.exe / WeChatStore.exe)")
            raise KeyExtractionError("未找到微信进程，请确认微信已启动")

        self._log(f"  找到微信主进程 PID: {main_pids}")

        import io, contextlib, logging as _logging
        for name in _logging.root.manager.loggerDict:
            if 'pywxdump' in name.lower() or 'wx_' in name.lower():
                _logging.getLogger(name).setLevel(_logging.CRITICAL)
        null_buf = io.StringIO()
        with contextlib.redirect_stderr(null_buf), \
             contextlib.redirect_stdout(null_buf):
            for pid in main_pids:
                info = get_info_details(pid, pywxdump.WX_OFFS)
                key = info.get('key')
                self._log(f"  PID {pid}: version={info.get('version','N/A')} "
                          f"wxid={info.get('wxid','N/A')} "
                          f"key={'YES' if key else 'NONE'}")
                if key and _is_valid_key(key):
                    self._key_wxid = info.get('wxid')
                    self._log(f"  PyWxDump 获取密钥成功 (wxid={self._key_wxid})")
                    for name in _logging.root.manager.loggerDict:
                        if 'pywxdump' in name.lower() or 'wx_' in name.lower():
                            _logging.getLogger(name).setLevel(_logging.NOTSET)
                    return key
        for name in _logging.root.manager.loggerDict:
            if 'pywxdump' in name.lower() or 'wx_' in name.lower():
                _logging.getLogger(name).setLevel(_logging.NOTSET)

        raise KeyExtractionError("PyWxDump: 微信主进程未返回有效密钥")

    @staticmethod
    def _find_test_shard() -> str | None:
        """Find a single MSG shard to verify extracted key against."""
        import os as _os
        from engine.wechat_scanner import WeChatScanner
        try:
            accounts = WeChatScanner().find_accounts()
            for acc in accounts:
                for shard in acc.shard_paths:
                    if _os.path.isfile(shard):
                        return shard
        except Exception:
            pass
        return None

    def _try_pymem(self) -> str:
        try:
            import pymem
            import pymem.exception
        except ImportError:
            raise ImportError("pymem not installed")

        self._log(f"  pymem 已安装")

        process_names = ("Weixin.exe", "WeChat.exe", "WeChatStore.exe", "WeChatAppEx.exe")
        for name in process_names:
            self._log(f"  查找进程: {name}...")
            try:
                pm = pymem.Pymem(name)
                self._log(f"  找到进程 {name} (PID: {pm.process_id})")
                key = self._scan_memory_for_key(pm)
                if key:
                    return key
                self._log(f"  未在 {name} 内存中找到密钥模式")
            except pymem.exception.ProcessNotFound:
                self._log(f"  进程未找到: {name}")
                continue
            except Exception as e:
                self._log(f"  pymem 异常 ({name}): {e}")
                continue

        raise KeyExtractionError(f"已尝试进程: {', '.join(process_names)}，均未找到密钥")

    def _scan_memory_for_key(self, pm) -> str | None:
        import re
        modules = list(pm.list_modules())
        wechat_modules = [m for m in modules if m.name.lower() in
                          ("wechat.exe", "wechat.dll", "wechatwin.dll",
                           "weixin.exe", "weixin.dll")]
        all_module_names = [m.name for m in modules]

        self._log(f"  总模块数: {len(modules)}")
        self._log(f"  微信相关模块: {[m.name for m in wechat_modules]}")

        if not wechat_modules:
            # Broaden: look for any module with 'wechat' in name
            wechat_modules = [m for m in modules if 'wechat' in m.name.lower()]
            self._log(f"  放宽搜索: {'找到' if wechat_modules else '未找到'}含'wechat'的模块")
            # If still none, look at all large modules
            if not wechat_modules:
                large = sorted(
                    [(m.name, m.SizeOfImage) for m in modules
                     if m.SizeOfImage > 5 * 1024 * 1024],
                    key=lambda x: -x[1]
                )
                self._log(f"  大模块 (>{5}MB): {large[:10]}")

        for module in wechat_modules:
            size_mb = module.SizeOfImage / (1024 * 1024)
            self._log(f"  扫描 {module.name} ({size_mb:.1f}MB)...")
            if module.SizeOfImage > 200 * 1024 * 1024:
                self._log(f"    跳过 (>200MB)")
                continue
            try:
                data = pm.read_bytes(module.lpBaseOfDll, module.SizeOfImage)
            except Exception as e:
                self._log(f"    读取失败: {e}")
                continue
            decoded = data.decode("ascii", errors="ignore")
            matches = re.findall(r'[0-9a-fA-F]{64}', decoded)
            self._log(f"    找到 {len(matches)} 个64字符hex候选")
            for match in matches:
                self._log(f"    hex候选: {match[:8]}...{match[-8:]}")
            # Also try without word boundaries (more permissive)
            if not matches:
                matches = re.findall(r'[0-9a-fA-F]{32}', decoded)
                self._log(f"    尝试32字符hex: 找到 {len(matches)} 个候选")
            if matches:
                # Verify each candidate against a test shard
                test_shard = self._find_test_shard()
                for match in matches:
                    self._log(f"    测试候选: {match[:8]}...{match[-8:]}")
                    if test_shard and _verify_key_on_shard(match, test_shard):
                        self._log(f"    验证通过!")
                        return match
                    self._log(f"    验证失败")
                self._log(f"    所有 {len(matches)} 个候选均验证失败")
                return None

        self._log(f"  扫描完成，未找到密钥")
        return None
