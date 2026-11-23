// CI only (build.yml, screens): a real left click at screen point x y (CGEvent, like a hand on the mouse), or a double
// click with a third argument 2, or only a move of the mouse with a 0 (menus follow the mouse):
//   osascript -l JavaScript tools/ci_click.js 776 195
//   osascript -l JavaScript tools/ci_click.js 300 120 2
// System Events' "click at" does not press SwiftUI controls, so the dialog checks click this way.
ObjC.import('CoreGraphics');

function post(type, point, count) {
  const e = $.CGEventCreateMouseEvent(null, type, point, $.kCGMouseButtonLeft);
  $.CGEventSetIntegerValueField(e, $.kCGMouseEventClickState, count);
  $.CGEventPost($.kCGHIDEventTap, e);
}

function run(argv) {
  const point = $.CGPointMake(Number(argv[0]), Number(argv[1]));
  const clicks = Number(argv[2] || 1);
  post($.kCGEventMouseMoved, point, 0);
  delay(0.15);
  for (let n = 1; n <= clicks; n++) {
    post($.kCGEventLeftMouseDown, point, n);
    delay(0.05);
    post($.kCGEventLeftMouseUp, point, n);
    delay(0.1);
  }
  return `clicked ${clicks}× at ${argv[0]},${argv[1]}`;
}
