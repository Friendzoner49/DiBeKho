-- CI only (build.yml, screens), after tools/ci_click.js clicked into the Phiếu xuất kho window: the keys of a person.
--   "pick": ↓ and Return in the ▾ menu just opened (the first customer)
--   "type": paste a customer's name into the customer box just clicked, then Tab
-- A screenshot then shows whether the other boxes were filled (user, 21/11/2026).
on run argv
	set mode to "pick"
	if (count of argv) > 0 then set mode to item 1 of argv
	tell application "System Events"
		tell process "DiBeKhoSwift"
			if mode is "pick" then
				key code 125 -- ↓: the first customer
				delay 0.3
				key code 36 -- Return
				log "picked the first customer from ▾"
			else
				set the clipboard to "Khách Mẫu" -- pasted: keystroke cannot type Vietnamese letters
				keystroke "v" using command down
				delay 0.5
				keystroke tab
				log "typed a customer's name"
			end if
		end tell
	end tell
end run
