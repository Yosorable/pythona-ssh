"""A small UIKit host for the offline terminal page."""

import builtins
import json
import queue
import weakref

from rubicon.objc import NSObject, ObjCClass, SEL, objc_method
from rubicon.objc.runtime import load_library

from .app import SSHApp
from .page import render_page


_WEBKIT = load_library("WebKit")


def value(receiver, name):
    item = getattr(receiver, name)
    return item() if callable(item) else item


def presenter():
    application = value(ObjCClass("UIApplication"), "sharedApplication")
    for scene in value(application.connectedScenes, "allObjects"):
        if not scene.isKindOfClass_(ObjCClass("UIWindowScene")) or scene.activationState != 0:
            continue
        for window in scene.windows:
            if value(window, "isKeyWindow"):
                controller = window.rootViewController
                while controller.presentedViewController is not None:
                    controller = controller.presentedViewController
                return controller
    raise RuntimeError("No active window is available.")


class PageHandler(NSObject, auto_rename=True):
    @objc_method
    def backTap(self):
        host = self.host_ref()
        if host:
            host.events.put({"event": "navigate", "page": "hosts"})

    @objc_method
    def closeTap(self):
        host = self.host_ref()
        if host:
            host.app.closed.set()

    @objc_method
    def resume_(self, notification):
        host = self.host_ref()
        if host and not host.app.closed.is_set():
            host.enqueue({"id": 0, "action": "resume"})

    @objc_method
    def userContentController_didReceiveScriptMessage_(self, controller, message):
        host = self.host_ref()
        if not host or host.app.closed.is_set() or not value(message.frameInfo, "isMainFrame"):
            return
        body = str(message.body)
        if len(body) > 300000:
            return
        try:
            request = json.loads(body)
        except (ValueError, TypeError):
            return
        if (isinstance(request, dict) and type(request.get("id")) is int
                and 0 <= request["id"] <= 2**53 - 1 and isinstance(request.get("action"), str)):
            host.enqueue(request)

    @objc_method
    def webViewWebContentProcessDidTerminate_(self, webview):
        host = self.host_ref()
        if host:
            host.app.closed.set()
            print("The terminal page was closed by iOS. Run main.py to reconnect.")


class WebTerminal:
    def __init__(self, store=None):
        self.requests = queue.Queue(maxsize=256)
        self.events = queue.Queue()
        self.app = SSHApp(store=store, emit=self.events.put)
        self.controller = self.navigation = self.webview = self.handler = None
        self.flush_pending = False

    def enqueue(self, request):
        try:
            self.requests.put_nowait(request)
        except queue.Full:
            self.events.put({"id": request["id"], "error": {"code": "bridge_busy", "detail": ""}})

    def open(self):
        bundle = value(ObjCClass("NSBundle"), "mainBundle")
        languages = value(bundle, "preferredLocalizations")
        language = str(languages[0]) if len(languages) else "en"
        page = render_page(language)
        self.controller = ObjCClass("UIViewController").alloc().init()
        self.controller.title = "Pythona SSH"
        self.controller.view.backgroundColor = value(ObjCClass("UIColor"), "systemBackgroundColor")
        configuration = ObjCClass("WKWebViewConfiguration").alloc().init()
        configuration.websiteDataStore = value(ObjCClass("WKWebsiteDataStore"), "nonPersistentDataStore")
        self.handler = PageHandler.alloc().init()
        self.handler.host_ref = weakref.ref(self)
        configuration.userContentController.addScriptMessageHandler_name_(self.handler, "ssh")
        close = ObjCClass("UIBarButtonItem").alloc().initWithImage_style_target_action_(
            ObjCClass("UIImage").systemImageNamed_("xmark"), 0, self.handler, SEL("closeTap"))
        close.tintColor = value(ObjCClass("UIColor"), "labelColor")
        self.controller.navigationItem.rightBarButtonItem = close
        view = self.controller.view
        webview = ObjCClass("WKWebView").alloc().initWithFrame_configuration_(view.bounds, configuration)
        self.webview = webview
        webview.navigationDelegate = self.handler
        webview.translatesAutoresizingMaskIntoConstraints = False
        webview.scrollView.contentInsetAdjustmentBehavior = 2
        webview.scrollView.bounces = False
        view.addSubview_(webview)
        # Resize the entire terminal viewport above the keyboard, including its key bar.
        ObjCClass("NSLayoutConstraint").activateConstraints_([
            webview.topAnchor.constraintEqualToAnchor_(view.safeAreaLayoutGuide.topAnchor),
            webview.leadingAnchor.constraintEqualToAnchor_(view.safeAreaLayoutGuide.leadingAnchor),
            webview.trailingAnchor.constraintEqualToAnchor_(view.safeAreaLayoutGuide.trailingAnchor),
            webview.bottomAnchor.constraintEqualToAnchor_(view.keyboardLayoutGuide.topAnchor),
        ])
        self.navigation = ObjCClass("UINavigationController").alloc().initWithRootViewController_(self.controller)
        self.navigation.overrideUserInterfaceStyle = 2  # UIUserInterfaceStyleDark
        self.navigation.modalPresentationStyle = 0
        value(ObjCClass("NSNotificationCenter"), "defaultCenter").addObserver_selector_name_object_(
            self.handler, SEL("resume:"), "UIApplicationDidBecomeActiveNotification", None)
        webview.loadHTMLString_baseURL_(page, None)
        presenter().presentViewController_animated_completion_(self.navigation, True, None)

    def _clipboard(self, action, payload):
        def perform():
            clipboard = value(ObjCClass("UIPasteboard"), "generalPasteboard")
            if action == "clipboard_read":
                text = value(clipboard, "string")
                return str(text) if text is not None else ""
            text = payload.get("text")
            if not isinstance(text, str) or len(text) > 1024 * 1024:
                raise ValueError("invalid_input")
            clipboard.string = text
            return None
        return builtins.run_on_ui(perform).wait()

    def set_page(self, payload):
        page = payload.get("page")
        title = payload.get("title", "Pythona SSH")
        if page not in ("hosts", "terminal") or not isinstance(title, str) or len(title) > 255:
            raise ValueError("invalid_request")

        def update():
            if self.controller is None:
                return
            self.controller.title = title if page == "terminal" else "Pythona SSH"
            self.controller.navigationItem.leftBarButtonItem = (
                ObjCClass("UIBarButtonItem").alloc().initWithImage_style_target_action_(
                    ObjCClass("UIImage").systemImageNamed_("chevron.left"), 0, self.handler, SEL("backTap"))
                if page == "terminal" else None
            )
        builtins.run_on_ui(update).wait()

    def process(self):
        for index in range(32):
            try:
                request = self.requests.get(timeout=0.016 if index == 0 else 0)
            except queue.Empty:
                break
            try:
                action, payload = request["action"], request.get("payload") or {}
                if action in ("clipboard_read", "clipboard_write"):
                    result = self._clipboard(action, payload)
                elif action == "set_page":
                    result = self.set_page(payload)
                else:
                    result = self.app.dispatch(action, payload)
                if request["id"]:
                    self.events.put({"id": request["id"], "result": result})
            except Exception as error:
                self.events.put({"id": request["id"], "error": {
                    "code": str(error) if isinstance(error, ValueError) else "operation_failed",
                    "detail": "" if isinstance(error, ValueError) else str(error)}})
        self.flush()

    def flush(self):
        if self.flush_pending or self.events.empty():
            return
        batch = []
        for _ in range(128):
            try:
                batch.append(self.events.get_nowait())
            except queue.Empty:
                break
        code = "window.sshBridge && window.sshBridge.receive(" + json.dumps(batch, ensure_ascii=True) + ")"
        self.flush_pending = True

        def deliver():
            try:
                if self.webview is not None and not self.app.closed.is_set():
                    self.webview.evaluateJavaScript_completionHandler_(code, None)
            finally:
                self.flush_pending = False
        builtins.run_on_ui(deliver)

    def close(self):
        if self.handler is not None:
            value(ObjCClass("NSNotificationCenter"), "defaultCenter").removeObserver_(self.handler)
        if self.webview is not None:
            self.webview.configuration.userContentController.removeScriptMessageHandlerForName_("ssh")
            self.webview.navigationDelegate = None
            self.webview.stopLoading()
        if self.navigation is not None and self.navigation.presentingViewController is not None:
            self.navigation.dismissViewControllerAnimated_completion_(False, None)
        self.controller = self.navigation = self.webview = self.handler = None


def main():
    if not hasattr(builtins, "run_on_ui"):
        raise RuntimeError("Run main.py inside Pythona, or use --preview on a desktop.")
    host = WebTerminal()
    try:
        builtins.run_on_ui(host.open).wait()
        while not host.app.closed.is_set():
            host.process()
    finally:
        host.app.close()
        builtins.run_on_ui(host.close).wait()
