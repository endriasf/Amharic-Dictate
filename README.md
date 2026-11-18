<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/banner_dark.png">
    <img src="assets/banner_light.png" width="520" alt="Amharic Dictate">
  </picture>
</p>

# Amharic Dictate

**Free, offline Amharic dictation for Windows, powered by the Amharic Speech-to-Text EFA v1 AI speech model.** Speak Amharic and your words appear
as text in Word, Outlook, Teams, your browser or any other program.

Free and open source.

- **AI speech recognition:** the built-in AI model *Amharic Speech-to-Text EFA v1* turns your
  speech into Amharic text. It's included in the installer.
- **Works offline:** the AI runs on your computer. Nothing you say is sent anywhere.
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
- **Microsoft Store** (recommended): open the Microsoft Store, search for **Amharic Dictate**, then
  click **Get**. The Store version is signed by Microsoft and updates itself.
- **Or** download **AmharicDictate-Setup-2.4.0.exe** from the
  [Releases page](https://github.com/endriasf/Amharic-Dictate/releases) and run it — for PCs where
  the Microsoft Store isn't available. No administrator rights are needed. Windows may show
  *"Windows protected your PC"* because this download isn't code-signed yet: click
  **More info → Run anyway**. This version tells you when an update is available.

After installing, Amharic Dictate opens with a start-up window while it loads, then waits in the
taskbar's system tray (bottom right, next to the clock; click **^** if you don't see its round icon).

| Icon colour | Meaning |
|---|---|
| Grey | Starting up (about 30–60 seconds) |
| Green | Ready |
| Red | Listening |
| Gold | Paused |

---

## 2. Dictate

1. Click where you want the text to go (for example a Word document).
2. Press **Ctrl + Alt + Space**. A box appears and the icon turns red.
3. Speak Amharic normally. Your words appear in the box as you speak.
4. Press **Ctrl + Alt + Space** again (or click **✓ Done**). The text is typed into your document.

The text also stays on the clipboard, so you can paste it again with **Ctrl + V**.

### Live dictation into Microsoft Word
When you start dictating while **Word** is the active window, your words go **straight into the
document** as you speak, at the cursor:

- Corrections you make in the dictation box (replace, remove, insert, join, punctuation, Undo)
  update the document immediately.
- You can also edit the dictated text **directly in Word**; the dictation box updates to match.
- Typing anywhere else in the document is never touched.
- Word's cursor follows your words, as if you were typing. **Click somewhere else** in the
  document (or type there) and keep talking: the next words go **at the new spot**, and the box
  starts fresh for that passage. Clicking inside the passage you are dictating keeps it as one.
- **✓ Done** simply finishes (the text is already there). **✕ Cancel** removes the dictated text.

Turn it off in **Settings → General → Live dictation into Microsoft Word**. In other programs, the
text is pasted when you finish.

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

## 5. Train it to your voice, add your own words, learn from corrections

All three are in one window: tray icon → **Voice profiles…**. Everything stays on your computer.

### 5a. Create your voice profile
The first time you start the app, it asks **"Who's dictating?"**. Type your name to create your
profile. To add another person, open **Voice profiles…** and click **New…** next to
**Who's dictating**. Each person's training, words and corrections are kept separately.

### 5b. Train the app to your voice
**Step 1: record the setup reading** (tab **1. Setup reading**)

1. A sentence is shown. Press **● Record** and read it aloud at your normal speed.
2. Press **■ Stop** when you finish.
3. Press **▶ Play back** to check it. If you stumbled, press **● Re-record**.
4. Press **✓ Save & next** for the next sentence, or **Skip sentence** to skip one.
5. Aim for **50 sentences** (5–10 minutes). Training needs at least 30. Reading more, up to 300,
   gives better accuracy. You can close the window and continue another day.

The level bar shows your microphone volume. The window warns you if a recording is too quiet or
too loud.

**Step 2: train** (tab **2. Train profile**)

1. Click **Start training**. It runs in the background, usually for **15–40 minutes**. You can keep
   working, and even keep dictating.
2. When it finishes, the app compares your voice profile with no profile on recordings it did not
   train on. If your profile is more accurate, it switches on automatically and the window shows
   the before and after results.
3. To turn your profile off, untick **Use this voice profile when dictating**.

Read more sentences later and click **Start training** again whenever you like. Each retraining
uses all your recordings.

### 5c. Add your own words (My words)
For names, places, organisations and terms the app gets wrong or underlines in red. There are two
ways to add them:

- **While dictating:** click the word in the dictation box, then click **★ My words**.
- **In the window:** open tab **3. My words**, type the word (or several words), then press
  **Add** or Enter.

To remove words, select them in the list and click **Remove selected**.

Words you add are preferred when the app is choosing between similar words, near-misses are
corrected to them automatically, and they are never marked as misspelled. The list belongs to
the profile, so each person has their own.

### 5d. Learn from your corrections
1. Open tab **4. Learning** and tick **Learn from my corrections**.
2. Dictate as usual. When you fix a word in the dictation box and then press **✓ Done**, the app
   saves that sentence's audio with your corrected text.
   - Dictations you **cancel** are never saved.
   - Sentences that are too unclear to match safely, such as sentences you rewrote completely,
     are skipped.
3. With **Retrain automatically after 25 new corrections** ticked, your profile improves itself in
   the background when you are not dictating. Otherwise, click **Start training** in tab 2
   whenever you want.

The tab shows how many corrections are saved. **Delete saved corrections** removes them; your
setup reading is kept. Untick **Learn from my corrections** before dictating anything you don't
want stored on the computer.

### 5e. Move a profile to another computer
Click **Export…** to save the profile as a .zip file. On the other computer, open
**Voice profiles…** and click **Import…**.

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

Everything you dictate is processed on your computer by the built-in AI model. Nothing is
uploaded, and no online AI service is used.

**Updates:** once a day the app asks GitHub for the version number of the newest release, so it can
tell you when an update is available (right-click the tray icon → **Download update…**). Nothing about
you or your dictation is sent, and nothing is downloaded or installed automatically. Turn this off in
**Settings**, or check by hand with **Check for updates** in the tray menu. To update, run the new
installer: your settings and voice profiles are kept.

Like any AI, the speech model can mishear words, especially names, rare words and noisy audio.
Check the text before you send or print it. Voice training and **My words** reduce mistakes. Dictation history is
**off** by default. Voice-profile recordings and corrections stay in your Windows user folder
(`%APPDATA%\AmharicDictate`) and can be deleted in **Voice profiles**.

---

## Licence and credits

- **App and built-in speech model:** © 2026 Endrias F. Abitte. App under the MIT licence
  (see [LICENSE](LICENSE)); speech model *Amharic Speech-to-Text EFA v1* under CC BY-SA 4.0.
  Trained from facebook/w2v-bert-2.0 (Meta, MIT) on WAXAL Amharic speech data (Google Research and
  partners; Amharic recordings by Digital Umuganda, CC BY-SA 4.0) and FLEURS (Google, CC BY 4.0).
- **Amharic dictionary:** Leipzig Corpora Collection (CC BY 4.0; D. Goldhahn, T. Eckart and
  U. Quasthoff, LREC 2012).
- Full list: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Developers: see [DEVELOPERS.md](DEVELOPERS.md) for running from source, building and training.
