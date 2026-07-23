import monitor as m

body = (
    '<html><div class="srp-results srp-list"><ul class="srp-results"></ul>'
    "<p>Es wurden keine Ergebnisse gefunden</p></div></html>"
)
items, err = m._parse_search_body(body, "test", "z80 leading")
assert items == [] and err is None, (items, err)
print("OK empty marker", err)

body2 = "<html>" + ("x" * 9000) + ' class="s-card__title" ' + "</html>"
items2, err2 = m._parse_search_body(body2, "test", "q")
assert items2 == [] and err2 is None, (items2, err2)
print("OK container no itm", err2)

body3 = "<html>" + ("y" * 9000) + "</html>"
items3, err3 = m._parse_search_body(body3, "test", "q")
assert items3 == [] and err3 == "blocked", (items3, err3)
print("OK stealth", err3)

print("all pass")
