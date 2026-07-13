---
name: rtl
description: >
  Formats all Hebrew and Arabic text output with proper right-to-left (RTL) direction.
  Use this skill whenever the user types /rtl, or asks for RTL support, Hebrew formatting,
  or right-to-left text direction. Also trigger when the user says "עברית מימין לשמאל",
  "תכתוב מימין", "RTL", or any variation requesting RTL text formatting.
---

# RTL — Right-to-Left Hebrew Formatting

When this skill is active, format ALL text output so Hebrew renders correctly right-to-left in the Claude desktop app.

## How it works

Prefix every line that contains Hebrew or Arabic characters with the Unicode RIGHT-TO-LEFT MARK (U+200F `‏`). This invisible character tells the renderer to treat the line as RTL.

## Rules

1. **Hebrew/Arabic lines**: Start each paragraph or line that contains Hebrew/Arabic with U+200F (the RTL mark character `‏`).

2. **Code blocks stay LTR**: Never add RTL marks inside fenced code blocks (``` or indented code). Code is always left-to-right.

3. **File paths stay LTR**: File paths, URLs, and terminal commands remain left-to-right — do not prefix them with RTL marks.

4. **English-only lines stay LTR**: Lines containing only English/Latin text get no RTL mark.

5. **Mixed lines**: If a line mixes Hebrew and English (e.g., a Hebrew sentence with an English term), prefix with U+200F — the Hebrew determines the base direction.

6. **Bullet points and lists**: Add the RTL mark after the markdown list marker (`- ‏` or `1. ‏`) so the list syntax is preserved but the text flows RTL.

7. **Headers**: Add the RTL mark after the `#` markers (`## ‏כותרת`).

## Example

Input intent: Explain what a variable is, in Hebrew.

Output:
```
‏משתנה (variable) הוא מקום בזיכרון שמאחסן ערך.

‏לדוגמה:

\```python
x = 42
name = "hello"
\```

‏בדוגמה הזו, `x` מאחסן מספר ו-`name` מאחסן מחרוזת.
```

Notice: Hebrew lines start with ‏ (U+200F), code block stays untouched.

## Persistence

Once activated via /rtl, apply these formatting rules to ALL subsequent responses in the conversation — the user should not need to re-invoke the skill each time. Continue applying RTL formatting until the user explicitly asks to stop or switches language entirely to English.
