-- CI only (build.yml, screens): on the open Phiếu xuất kho window, pick the first customer from ▾ with real clicks,
-- or (argument "type") click the customer box and type a customer's name, so a screenshot shows whether the
-- other boxes were filled (user, 21/11/2026). Prints what it did; never fails the build by itself.
on run argv
	set mode to "pick"
	if (count of argv) > 0 then set mode to item 1 of argv
	tell application "System Events"
		tell process "DiBeKhoSwift"
			set frontmost to true
			delay 1
			set w to front window
			set found to {}
			repeat with e in (entire contents of w)
				try
					if role of e is in {"AXMenuButton", "AXPopUpButton"} then set end of found to e
				end try
			end repeat
			log "menu buttons: " & (count of found) & " in window " & (name of w)
			if mode is "pick" then
				set mb to item 1 of found
				click mb
				delay 1
				click menu item 1 of menu 1 of mb
				log "picked the first customer from ▾"
			else
				repeat with e in (entire contents of w)
					try
						if role of e is "AXTextField" then
							click e
							exit repeat
						end if
					end try
				end repeat
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
