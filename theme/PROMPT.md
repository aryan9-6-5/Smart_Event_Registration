Attached is the event banner. Fill theme/theme.json using exactly these keys
(copy theme/theme.example.json as the starting point).

Rules:
- primary must be a colour that appears in the banner
- text on surface and primary_text on primary must each reach 4.5:1 contrast
- do not add keys; do not touch status colours (they are fixed in code)
- font.family may only contain letters, digits and spaces (a Google Fonts family)

Return only the JSON. The app validates it at startup and falls back to the
default blue theme if anything is wrong (the reason is printed in the server log).
