# Amharic Dictate

**Free, offline Amharic dictation for Windows.** Speak Amharic and your words appear as text in
Word, Outlook, Teams, your browser or any other program.

**Created by Endrias F. Abitte.** Free and open source. If you share or build on it, please keep the
credit: *Amharic Dictate by Endrias F. Abitte*.

- **Works offline:** everything runs on your computer. Nothing you say is sent anywhere.
- **Built-in speech model:** *Amharic Speech-to-Text EFA v1*, included in the installer.
- **Easy corrections:** click any word to fix, remove or replace it.
- **Learns your voice:** optional voice profile for better accuracy.

---

## 1. Install

### What you need
- Windows 10 or 11 (64-bit)
- 8 GB of memory recommended (4 GB minimum)
- About 4 GB of free disk space
- A microphone. A headset gives the best results.

### Download
- **Microsoft Store** (recommended): search for **Amharic Dictate**, then click **Get**.
- **Or** download **AmharicDictate-Setup.exe** from the
  [Releases page](https://github.com/endriasf/amharic-dictate/releases) and run it.
  No administrator rights are needed. If Windows shows *"Windows protected your PC"*, click
  **More info → Run anyway**.

After installing, Amharic Dictate starts automatically. A **microphone icon** appears in the
taskbar's system tray (bottom right, next to the clock; click **^** if you don't see it).

| Icon colour | Meaning |
|---|---|
| Grey | Starting up (about 30–60 seconds) |
| Green | Ready |
| Red | Listening |

---

## 2. Dictate

1. Click where you want the text to go (for example a Word document).
2. Press **Ctrl + Alt + Space**. A box appears and the icon turns red.
3. Speak Amharic normally. Your words appear in the box as you speak.
4. Press **Ctrl + Alt + Space** again (or click **✓ Done**). The text is typed into your document.

The text also stays on the clipboard, so you can paste it again with **Ctrl + V**.

### Buttons in the dictation box
| Button | What it does |
|---|---|
| ↶ Undo | Undo the last change (up to 14 steps) |
| ⏸ Pause | Stop listening for a moment, for example to talk to someone. Click again to resume |
| ⌫ Delete word | Delete the last word |
| ⧉ Copy | Copy the text without closing the box |
| ። ፣ ፤ ? ! « » ( ) | Insert punctuation |
| ✕ Cancel | Close the box and throw the text away |
| ✓ Done | Put the text into your document |

### Keyboard shortcuts
| Keys | Action |
|---|---|
| Ctrl + Alt + Space | Start / finish dictation |
| Ctrl + Alt + P | Pause / resume |
| Ctrl + Alt + Backspace | Delete the last word |
| Ctrl + Alt + Z | Undo |

You can change the shortcuts, or switch to **push-to-talk** (hold a key while speaking), in
**Settings**.

---

## 3. Voice commands

Say these words and the app inserts the mark instead of the words:

| Say | You get |
|---|---|
| አራት ነጥብ | ። |
| ነጠላ ሰረዝ | ፣ |
| ድርብ ሰረዝ | ፤ |
| የጥያቄ ምልክት | ? |
| ቃለ አጋኖ | ! |
| ቅንፍ ክፈት … ቅንፍ ዝጋ | ( … ) |
| ጥቅስ ክፈት … ጥቅስ ዝጋ | « … » |
| ትእምርተ ጥቅስ | « the first time, » the next time |
| አዲስ መስመር | New line |
| አዲስ አንቀጽ | New paragraph |
| ያንን ሰርዝ | Delete the last word |

**Numbers:** spoken numbers become digits. For example ሃያ አራት → 24, ሁለት መቶ ሀምሳ → 250.
A single small number such as "አንድ ሰው" stays as words.

---

## 4. Fix mistakes

In the dictation box, while you are still dictating:

- **Click a word:** it is highlighted. Then either **say the correct word**, click one of the
  **suggestions**, or use the buttons: **🗑 Remove**, **⇤ Join previous**, **Join next ⇥**,
  **➕ Insert before / after**, **★ My words**.
- **Click the space between two words:** say the words you want to insert there, or click
  **Join words** to remove the space.
- **Click a punctuation mark:** remove it, or change it to another mark.

Colours in the box:
- **Red underline:** probably misspelled. Click the word to see corrections.
- **Orange:** the app wasn't sure it heard this word correctly.

---

## 5. Voice profile (better accuracy)

The app can learn your voice. Open it from the tray icon → **Voice profiles…**.

1. **Setup reading:** read about 50 sentences aloud (5–10 minutes). Reading more, up to 300,
   gives better accuracy. You can stop and continue another day.
2. **Train profile:** click **Start training**. It runs in the background on your computer
   (usually 15–40 minutes) and you can keep working.
3. When it finishes, your profile switches on by itself, but only if it is more accurate for you
   than no profile. The window shows the before and after results.

More options in the same window:
- **Who's dictating:** each person can have their own profile.
- **My words:** add names, places and terms you use often. The app prefers them and never marks
  them as misspelled.
- **Learning:** tick **Learn from my corrections** to let the app improve from the words you fix.
  Your corrections are saved on your computer only.
- **Export / Import:** move a profile to another computer.

---

## 6. Settings

Tray icon → **Settings**:
- Hotkeys and push-to-talk
- How text is inserted: when you finish (default), after each sentence, or to the clipboard only
- Spelling check and automatic spelling fixes
- Speech model and performance options
- Start with Windows

---

## 7. Tips and troubleshooting

| Problem | Try this |
|---|---|
| Nothing appears when I speak | Check the microphone in **Windows Settings → System → Sound → Input**. Speak a little closer to the microphone |
| Words are wrong | Speak at a steady pace, use a headset, do the voice-profile setup, add names to **My words** |
| Background voices get typed | Use **⏸ Pause** or push-to-talk mode |
| Text doesn't appear in a program | Programs running as Administrator block typing from normal apps. Use **⧉ Copy** and paste with Ctrl + V |
| Amharic letters show as boxes | Use an Amharic-capable font such as **Ebrima** or **Nyala** (built into Windows) |

---

## Privacy

Everything you dictate is processed on your computer. Nothing is uploaded. Dictation history is
**off** by default. Voice-profile recordings and corrections stay in your Windows user folder
(`%APPDATA%\AmharicDictate`) and can be deleted in **Voice profiles**.

---

## Licence and credits

- **App:** MIT licence, © 2026 **Endrias F. Abitte** (see [LICENSE](LICENSE)).
- **Built-in speech model:** *Amharic Speech-to-Text EFA v1* by **Endrias F. Abitte**, CC BY-SA 4.0.
  Trained from facebook/w2v-bert-2.0 (Meta, MIT) on WAXAL Amharic speech data (Google Research and
  partners; Amharic recordings by Digital Umuganda, CC BY-SA 4.0) and FLEURS (Google, CC BY 4.0).
- **Amharic dictionary:** Leipzig Corpora Collection (CC BY 4.0; D. Goldhahn, T. Eckart and
  U. Quasthoff, LREC 2012) and the GNU Aspell Amharic word list by Daniel Yacob / Ge'ez Frontier
  Foundation (public domain).
- Full list: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Developers: see [DEVELOPERS.md](DEVELOPERS.md) for running from source, building and training.
