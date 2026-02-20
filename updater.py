"""GitHub release checker and installer (stdlib only, works on 2.79+)."""

import json
import os
import shutil
import tempfile
import threading
import traceback
import zipfile

try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError, HTTPError
except ImportError:
    from urllib2 import urlopen, Request, URLError
    HTTPError = URLError

GITHUB_REPO = "Epic-Fight/blender-json-exporter"
API_URL = ("https://api.github.com/repos/%s/releases/latest"
           % GITHUB_REPO)
USER_AGENT = "EpicFight-Blender-Addon-Updater"

_bg_thread = None
_bg_result = None
_bg_done = False


def _urlopen_safe(url, timeout=15):
    """Try multiple SSL strategies since some Blender builds ship broken SSL."""
    req = Request(url) if isinstance(url, str) else url
    req.add_header('User-Agent', USER_AGENT)

    errors = []

    try:
        return urlopen(req, timeout=timeout)
    except Exception as e:
        errors.append("Standard: %s" % str(e))

    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        print("EF-UPDATE: trying unverified SSL")
        return urlopen(req, timeout=timeout, context=ctx)
    except Exception as e:
        errors.append("Unverified: %s" % str(e))

    try:
        import ssl
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS)
        except AttributeError:
            ctx = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        ctx.verify_mode = ssl.CERT_NONE
        return urlopen(req, timeout=timeout, context=ctx)
    except Exception as e:
        errors.append("Minimal: %s" % str(e))

    http_url = url
    if isinstance(http_url, str):
        http_url = http_url.replace('https://', 'http://', 1)
    elif hasattr(http_url, 'full_url'):
        http_url = Request(
            http_url.full_url.replace('https://', 'http://', 1))
        http_url.add_header('User-Agent', USER_AGENT)

    try:
        print("EF-UPDATE: trying plain HTTP (no SSL)")
        return urlopen(http_url, timeout=timeout)
    except Exception as e:
        errors.append("HTTP: %s" % str(e))

    raise RuntimeError(
        "Cannot connect to GitHub. SSL may be broken in this "
        "Blender build. Check for updates manually at "
        "https://github.com/%s/releases  --  Details: %s"
        % (GITHUB_REPO, " | ".join(errors)))


def parse_version(tag):
    tag = tag.strip().lstrip('vV')
    parts = []
    for p in tag.split('.'):
        try:
            parts.append(int(p))
        except ValueError:
            break
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def check_for_update(current_version):
    info = {
        'update_available': False,
        'latest_version': None,
        'latest_tag': '',
        'release_name': '',
        'release_notes': '',
        'download_url': '',
        'html_url': '',
        'error': None,
    }

    print("EF-UPDATE: checking GitHub for updates...")
    print("EF-UPDATE: current version: %s" % str(current_version))

    try:
        resp = _urlopen_safe(API_URL)
        raw = resp.read().decode('utf-8')
        data = json.loads(raw)

        tag = data.get('tag_name', '')
        latest = parse_version(tag)

        info['latest_version'] = latest
        info['latest_tag'] = tag
        info['release_name'] = data.get('name', '') or tag
        info['download_url'] = data.get('zipball_url', '')
        info['release_notes'] = data.get('body', '') or ''
        info['html_url'] = data.get('html_url', '')
        info['update_available'] = (latest > tuple(current_version))

        print("EF-UPDATE: latest tag: '%s', name: '%s'"
              % (tag, info['release_name']))
        print("EF-UPDATE: update_available: %s"
              % info['update_available'])

    except HTTPError as e:
        if hasattr(e, 'code') and e.code == 404:
            info['error'] = ("No releases found on GitHub. "
                             "Create a release at "
                             "https://github.com/%s/releases"
                             % GITHUB_REPO)
            print("EF-UPDATE: 404 - no releases found")
        else:
            info['error'] = "GitHub API error: %s" % str(e)
            print("EF-UPDATE: HTTP error: %s" % str(e))
    except Exception as e:
        info['error'] = str(e)
        print("EF-UPDATE: error: %s" % str(e))

    return info


def check_for_update_background(current_version):
    global _bg_thread, _bg_result, _bg_done
    _bg_result = None
    _bg_done = False

    def _worker():
        global _bg_result, _bg_done
        try:
            _bg_result = check_for_update(current_version)
        except Exception as e:
            print("EF-UPDATE: background thread error: %s" % str(e))
            _bg_result = {
                'update_available': False,
                'error': str(e),
            }
        _bg_done = True
        print("EF-UPDATE: background thread finished")

    print("EF-UPDATE: starting background check thread")
    _bg_thread = threading.Thread(target=_worker)
    _bg_thread.daemon = True
    _bg_thread.start()


def get_background_result():
    global _bg_thread
    if _bg_done:
        _bg_thread = None
        return _bg_result
    return None


def is_checking():
    return _bg_thread is not None and _bg_thread.is_alive()


def install_update(download_url, addon_dir):
    print("EF-UPDATE: downloading from %s" % download_url)

    tmp_dir = None
    try:
        resp = _urlopen_safe(download_url, timeout=60)

        tmp_dir = tempfile.mkdtemp(prefix='epicfight_update_')
        zip_path = os.path.join(tmp_dir, 'update.zip')

        with open(zip_path, 'wb') as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)

        extract_dir = os.path.join(tmp_dir, 'extracted')
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)

        # gitHub zipballs have a single top-level directory
        source_dir = extract_dir
        entries = os.listdir(extract_dir)
        if (len(entries) == 1
                and os.path.isdir(
                    os.path.join(extract_dir, entries[0]))):
            source_dir = os.path.join(extract_dir, entries[0])

        if not os.path.isfile(
                os.path.join(source_dir, '__init__.py')):
            found = False
            for root, dirs, files in os.walk(extract_dir):
                if ('__init__.py' in files
                        and 'compat.py' in files):
                    source_dir = root
                    found = True
                    break
            if not found:
                return (False,
                        "Archive does not contain recognizable "
                        "addon files.")

        copied = 0
        for fname in os.listdir(source_dir):
            if not fname.endswith('.py'):
                continue
            src = os.path.join(source_dir, fname)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(addon_dir, fname)
            shutil.copy2(src, dst)
            copied += 1
            print("EF-UPDATE: copied %s" % fname)

        if copied == 0:
            return (False, "No Python files found in the update.")

        return (True,
                "Updated %d file(s). Restart Blender to apply."
                % copied)

    except Exception as e:
        traceback.print_exc()
        return (False, "Update failed: %s" % str(e))

    finally:
        if tmp_dir and os.path.isdir(tmp_dir):
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass