import sublime
import sublime_plugin
from collections import defaultdict
import struct
import imghdr
import base64
import urllib.request
import urllib.parse
import io
import os.path
import re


DEBUG = True

PLUGIN_ID = "inline-image"


def debug(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


settings_file = "Inline Images.sublime-settings"


def get_settings():
    return sublime.load_settings(settings_file)


class InlineImagesPlugin(sublime_plugin.EventListener):
    def init_x(self, view):
        if view.is_loading():
            debug(f"Delaying initialization again...")
            sublime.set_timeout_async(lambda: self.init_x(view), 50)
            return
        settings = get_settings()
        show_local = settings.get("show_local_images_on_load", False)
        show_remote = settings.get("show_remote_images_on_load", False)
        if not show_local and not show_remote:
            return
        if not self._should_run_for_view(settings, view):
            return
        self._update_images(settings, view, show_local=show_local, show_remote=show_remote)

    def on_init(self, views):
        for view in views:
            self.init_x(view)

    def on_load_async(self, view):
        self.init_x(view)

    def on_post_save(self, view):
        settings = get_settings()
        show_local = settings.get("show_local_images_on_post_save")
        show_remote = settings.get("show_remote_images_on_post_save")
        if not show_local and not show_remote:
            return
        if not self._should_run_for_view(settings, view):
            return
        self._update_images(settings, view, show_local=show_local, show_remote=show_remote)

    def on_close(self, view):
        ImageHandler.on_close(view)

    def on_reload(self, view):
        ImageHandler.on_close(view)

    def _should_run_for_view(self, settings, view):
        syntax_filter = settings.get("syntax_filter")
        # syntax_filter can be either a list or single string
        if isinstance(syntax_filter, str):
            syntax_filter = [syntax_filter]
        syntax = view.syntax()
        if syntax:
            return syntax.name not in syntax_filter
        return False

    def _update_images(self, settings, view, **kwargs):
        max_width = settings.get("img_maxwidth", 1024)
        debug(
            f"file_name {view.file_name()}, layout_extent: {view.layout_extent()}"
            f", viewport_extent: {view.viewport_extent()}"
        )
        # Note: Excessive size will cause the ST3 window to become blank
        # unrecoverably. 1024 apperas to be a safe limit,
        # but can possibly go higher.
        if not max_width or max_width < 0:
            max_width = 1024
        view_width = view.viewport_extent()[0]
        if view_width > 0:
            max_width = min(max_width, view_width)
        base_path = settings.get("base_path", None)
        ImageHandler.show_images(
            view,
            max_width=max_width,
            show_local=kwargs.get("show_local", False),
            show_remote=kwargs.get("show_remote", False),
            base_path=base_path,
        )


class ImageHandler:
    """
    Static class to bundle image handling.
    """

    # Maps view IDs to sublime.PhantomSet
    phantomset_from_view = dict()
    # Cached remote URL image data. Kept even if not rendered.
    urldata = defaultdict(dict)

    @staticmethod
    def show_images(view, max_width=None, show_local=True, show_remote=False, base_path=""):
        ImageHandler._erase_phantoms(view)
        debug("show_images")
        if not show_local and not show_remote:
            debug("doing nothing")
            return

        phantoms = []
        comment_regs = view.find_by_selector("comment.line")
        debug(f"Sublime reports {len(comment_regs)} comment line regions")
        # for region in comment_regs:
        #     s = view.substr(region).replace('\n', '\\n')
        #     debug(f"  Region: {s}")

        # Sublime will join adjacent regions.
        # Split the region into lines. Each region will end with a newline.
        debug(f"Split into lines")

        def split_region(region):
            rel_p = view.substr(region)
            offset = region.begin()
            newlines = [(offset + i + 1) for i, char in enumerate(rel_p) if char == "\n"]
            newlines = [offset] + newlines
            if not rel_p.endswith("\n"):
                newlines += [offset + len(rel_p) + 1]
            s = rel_p.replace("\n", "\\n")
            lines = list(zip(newlines[:-1], newlines[1:]))
            debug(f'  split_region("{s}") -> {lines}')
            return [sublime.Region(i, j - 1) for (i, j) in lines]

        comment_regs = [
            sub_region for region in comment_regs for sub_region in split_region(region)
        ]
        # debug(f'comment_regs: {comment_regs}')
        for region in reversed(comment_regs):
            ttype = None
            urldata = None
            rel_p = view.substr(region)
            # ![Alt text](https://assets.digitalocean.com/articles/alligator/boo.svg "a title")
            debug(f'Region string: "{rel_p}"')

            if "(<" in rel_p:
                match_obj = re.search(r"!\[.*\]\(<(?P<link>[^>]*)>[^\)]*\)", rel_p)
                if not match_obj:
                    continue
                rel_p = match_obj.group("link")
            else:
                match_obj = re.search(r"!\[.*\]\((?P<link>[^ ]*)[^\)]*\)", rel_p)
                if not match_obj:
                    continue
                rel_p = match_obj.group("link")
            debug(f'Matched an image. link: "{rel_p}"')

            # If an image link is enclosed in <> to tolerate spaces in it,
            # then the > appears at the end of rel_p for some reason.
            # This character makes the link invalid, so it must be removed
            if rel_p[-1] == ">":
                rel_p = rel_p[0:-1]

            # (Windows) cutting the drive letter from the path,
            # otherwise urlparse interprets it as a scheme (like 'file' or 'http')
            # and generates a bogus url object like:
            # url= ParseResult(scheme='c', netloc='', path='/path/image.png', params='', query='', fragment='')
            drive_letter, rel_p = os.path.splitdrive(rel_p)

            url = urllib.parse.urlparse(rel_p)
            if url.scheme and url.scheme != "file":
                if not show_remote:
                    continue

                # We can't render SVG images, so skip the request
                # Note: not all URLs that return SVG end with .svg
                # We could use a HEAD request to check the Content-Type before
                # downloading the image, but the size of an SVG is typically
                # so small to not be worth the extra request
                if url.path.endswith(".svg"):
                    continue

                debug("image url", rel_p)
                data = ImageHandler.urldata[view.id()].get(rel_p)
                if not data:
                    try:
                        data = urllib.request.urlopen(rel_p)
                    except Exception as e:
                        debug("Failed to open URL {}:".format(rel_p), e)
                        continue

                    try:
                        data = data.read()
                    except Exception as e:
                        debug("Failed to read data from URL {}:".format(rel_p), e)
                        continue

                try:
                    w, h, ttype = get_image_size(io.BytesIO(data))
                except Exception as e:
                    msg = "Failed to get_image_size for data from URL {}"
                    debug(msg.format(rel_p), e)
                    continue

                FMT = """
                    <img src="data:image/{}" class="centerImage" {}>
                """
                b64_data = base64.encodestring(data).decode("ascii")
                b64_data = b64_data.replace("\n", "")

                img = "{};base64,{}".format(ttype, b64_data)
                urldata = data
            else:
                if not show_local:
                    continue

                # Convert relative paths to be relative to the current file
                # or project folder.
                # NOTE: if the current file or project folder can't be
                # determined (e.g. if the view content is not in a project and
                # hasn't been saved), then it will anchor to /.
                path = url.path

                # Force paths to be prefixed with base_path if it was provided
                # in settings.
                if base_path:
                    path = os.path.join(base_path, path)

                if not os.path.isabs(path):
                    folder = get_path_for(view)
                    path = os.path.join(folder, path)
                path = os.path.normpath(path)
                # (Windows) Adding back the drive letter that was cut from the path before
                path = drive_letter + path

                url = url._replace(scheme="file", path=path)

                FMT = """
                    <img src="{}" class="centerImage" {}>
                """
                try:
                    w, h, ttype = get_file_image_size(path)
                except Exception as e:
                    debug("Failed to load {}:".format(path), e)
                    continue
                img = urllib.parse.urlunparse(url)

                # On Windows, urlunparse adds a third slash after 'file://' for some reason
                # This breaks the image url, so it must be removed
                # splitdrive() detects windows because it only returns something if the
                # path contains a drive letter
                if os.path.splitdrive(path)[0]:
                    img = img.replace("file:///", "file://", 1)

            if not ttype:
                debug("unknown ttype")
                continue

            # TODO -- handle custom sizes better
            # If only width or height are provided, scale the other dimension
            # properly
            # Width defined in custom size should override max_width
            line_region = view.line(region)
            imgattr = check_imgattr(view, line_region, region)
            if not imgattr and w > 0 and h > 0:
                if max_width and w > max_width:
                    h *= max_width / w
                    w = max_width
                imgattr = 'width="{}" height="{}"'.format(w, h)

            # Force the phantom image view to append past the end of the line
            # Otherwise, the phantom image view interlaces in between
            # word-wrapped lines
            line_region.a = line_region.b

            debug("region", region)
            debug("line_region", line_region)

            html_img = FMT.format(img, imgattr)

            debug(f"Creating phantom {html_img} at {line_region.b}")
            phantoms.append(sublime.Phantom(line_region, html_img, sublime.LAYOUT_BLOCK))
            if urldata is not None:
                ImageHandler.urldata[view.id()][rel_p] = urldata
        debug(f"We have {len(phantoms)} phantoms: {phantoms}")
        if view.id() not in ImageHandler.phantomset_from_view:
            ImageHandler.phantomset_from_view[view.id()] = sublime.PhantomSet(view, PLUGIN_ID)
        ImageHandler.phantomset_from_view[view.id()].update(phantoms)

    @staticmethod
    def hide_images(view):
        ImageHandler._erase_phantoms(view)

    @staticmethod
    def on_close(view):
        ImageHandler._erase_phantoms(view)
        ImageHandler.urldata.pop(view.id(), None)

    @staticmethod
    def _erase_phantoms(view):
        if view.id() in ImageHandler.phantomset_from_view:
            del ImageHandler.phantomset_from_view[view.id()]
        # Cached URL data is kept


def check_imgattr(view, line_region, link_region=None):
    # find attrs for this link
    full_line = view.substr(line_region)
    link_till_eol = full_line[link_region.a - line_region.a :]
    # find attr if present
    m = re.match(r".*\)\{(.*)\}", link_till_eol)
    if m:
        return m.groups()[0]
    return ""


def get_file_image_size(img):
    with open(img, "rb") as f:
        return get_image_size(f)


def get_image_size(f):
    """
    Determine the image type of img and return its size.
    """
    head = f.read(24)
    ttype = None

    debug(str(head))
    debug(str(head[:4]))
    debug(head[:4] == b"<svg")

    if imghdr.what("", head) == "png":
        debug("detected png")
        ttype = "png"
        check = struct.unpack(">i", head[4:8])[0]
        if check != 0x0D0A1A0A:
            return None, None, ttype
        width, height = struct.unpack(">ii", head[16:24])
    elif imghdr.what("", head) == "gif":
        debug("detected gif")
        ttype = "gif"
        width, height = struct.unpack("<HH", head[6:10])
    elif imghdr.what("", head) == "jpeg":
        debug("detected jpeg")
        ttype = "jpeg"
        try:
            f.seek(0)  # Read 0xff next
            size = 2
            ftype = 0
            while not 0xC0 <= ftype <= 0xCF:
                f.seek(size, 1)
                byte = f.read(1)
                while ord(byte) == 0xFF:
                    byte = f.read(1)
                ftype = ord(byte)
                size = struct.unpack(">H", f.read(2))[0] - 2
            # SOFn block
            f.seek(1, 1)  # skip precision byte.
            height, width = struct.unpack(">HH", f.read(4))
        except Exception as e:
            debug("determining jpeg image size failed", e)
            return None, None, ttype
    elif head[:4] == b"<svg":
        debug("detected svg")
        # SVG is not rendered by ST3 in phantoms.
        # The SVG would need to be rendered as png/jpg separately, and its data
        # placed into the phantom
        return None, None, None
    else:
        debug("unable to detect image")
        return None, None, None
    return width, height, ttype


def get_path_for(view):
    """
    Returns the path of the current file in view.
    Returns / if no path is found
    """
    if view.file_name():
        return os.path.dirname(view.file_name())
    if view.window().project_file_name():
        return os.path.dirname(view.window().project_file_name())
    return "/"


class InlineImagesShowCommand(sublime_plugin.TextCommand):
    """
    Show local images inline.
    """

    def run(self, edit, **kwargs):
        settings = get_settings()
        max_width = settings.get("img_maxwidth", None)
        show_local = kwargs.get("show_local", True)
        show_remote = kwargs.get("show_remote", False)
        base_path = settings.get("base_path", None)
        ImageHandler.show_images(
            self.view,
            show_local=show_local,
            show_remote=show_remote,
            max_width=max_width,
            base_path=base_path,
        )


class InlineImagesHideCommand(sublime_plugin.TextCommand):
    """
    Hide all shown images.
    """

    def run(self, edit):
        ImageHandler.hide_images(self.view)
