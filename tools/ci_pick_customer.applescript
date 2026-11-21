-- CI only (build.yml, screens): on the open Phiếu xuất kho window (1024×768 runner screen, window where the app puts
-- it), pick the first customer from ▾ with a real click and the keyboard, or (argument "type") click the customer box,
-- paste a customer's name and press Tab, so a screenshot shows whether the other boxes were filled (user, 21/11/2026).
-- The positions come from the CI screenshot screen-19-issue-*.png. Prints what it did.
on run argv
	set mode to "pick"
	if (count of argv) > 0 then set mode to item 1 of argv
	tell application "System Events"
		tell process "DiBeKhoSwift"
			set frontmost to true
			delay 1
			set w to front window
			log "window " & (name of w) & " at " & ((position of w) as text) & " size " & ((size of w) as text)
			set {wx, wy} to position of w
			if mode is "pick" then
				click at {wx + 751, wy + 163} -- the ▾ next to the customer box
				delay 1
				key code 125 -- ↓: the first customer
				delay 0.3
				key code 36 -- Return
				log "picked the first customer from ▾"
			else
				click at {wx + 425, wy + 163} -- the customer box
				delay 0.5
				set the clipboard to "Khách Mẫu" -- pasted: keystroke cannot type Vietnamese letters
				keystroke "v" using command down
				delay 0.5
				keystroke tab
				log "typed a customer's name"
			end if
		end tell
	end tell
end run
