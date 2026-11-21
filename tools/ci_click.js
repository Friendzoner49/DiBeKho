// CI only (build.yml, screens): a real left click at screen point x y (CGEvent, like a hand on the mouse):
//   osascript -l JavaScript tools/ci_click.js 776 195
// System Events' "click at" does not press SwiftUI controls, so the issue-window check clicks this way.
ObjC.import('CoreGraphics');

function run(argv) {
  const point = $.CGPointMake(Number(argv[0]), Number(argv[1]));
  for (const type of [$.kCGEventMouseMoved, $.kCGEventLeftMouseDown, $.kCGEventLeftMouseUp]) {
    $.CGEventPost($.kCGHIDEventTap, $.CGEventCreateMouseEvent(null, type, point, $.kCGMouseButtonLeft));
    delay(0.15);
  }
  return `clicked at ${argv[0]},${argv[1]}`;
}
