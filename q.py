import os, csv, time, sqlite3, threading, random, string

# ====== Игнорируем системный прокси только для этого бота ======
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
for _v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
           "ALL_PROXY", "all_proxy"):
    os.environ.pop(_v, None)

import requests
_orig_request = requests.Session.request
def _no_proxy_request(self, *a, **kw):
    kw["proxies"] = {"http": None, "https": None}
    return _orig_request(self, *a, **kw)
requests.Session.request = _no_proxy_request
# ===============================================================

import telebot
from telebot import apihelper, types

# ============ КОНФИГ ============
BOT_TOKEN = "1780288466:LCWJt3cKu1SYbBhj3H4klKGauTWyHSumHgP"
BOT_API_BASE = "https://95-163-153-173.sslip.io"
ADMIN_ID = 1780285990
COOLDOWN = 15

apihelper.API_URL = BOT_API_BASE + "/bot{0}/{1}"
apihelper.FILE_URL = BOT_API_BASE + "/file/bot{0}/{1}"
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

# ============ БАЗА ============
DB = "bot.db"
_lock = threading.Lock()
_db = sqlite3.connect(DB, check_same_thread=False)
_db.row_factory = sqlite3.Row
_db.executescript("""
CREATE TABLE IF NOT EXISTS tickets(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE, user_id INTEGER, chat_id INTEGER, username TEXT,
    text TEXT, target TEXT, status TEXT DEFAULT 'new',
    hidden INTEGER DEFAULT 0, created INTEGER);
CREATE TABLE IF NOT EXISTS questions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE, user_id INTEGER, chat_id INTEGER, username TEXT,
    text TEXT, answer TEXT DEFAULT '', status TEXT DEFAULT 'new',
    hidden INTEGER DEFAULT 0, created INTEGER);
CREATE TABLE IF NOT EXISTS banned(user_id INTEGER PRIMARY KEY, ts INTEGER);
""")
_db.commit()

def q(sql, a=(), one=False):
    with _lock:
        r = _db.execute(sql, a).fetchall()
    return (r[0] if r else None) if one else r

def x(sql, a=()):
    with _lock:
        _db.execute(sql, a)
        _db.commit()

def gen_code():
    chars = string.ascii_uppercase + string.digits
    for _ in range(50):
        code = f"{''.join(random.choices(chars, k=4))}-{''.join(random.choices(chars, k=4))}"
        if not q("SELECT 1 FROM tickets WHERE code=?", (code,), one=True) and \
           not q("SELECT 1 FROM questions WHERE code=?", (code,), one=True):
            return code
    return f"{int(time.time())}-X"

STATUS = {"new":"🆕 Новая","in_work":"🔧 В работе","issued":"✅ Выдана",
          "rejected":"❌ Отклонена","closed":"🔒 Закрыта"}
QSTATUS = {"new":"🆕 Без ответа","answered":"✅ Отвечен","closed":"🔒 Закрыт"}

states = {}
cooldown = {}

# ============ КЛАВИАТУРЫ ============
def main_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("📝 Подать заявку на NFT", callback_data="n:new"))
    kb.add(types.InlineKeyboardButton("💬 Задать личный вопрос", callback_data="q:new"))
    kb.add(types.InlineKeyboardButton("📋 Мои заявки", callback_data="my:tickets"))
    kb.add(types.InlineKeyboardButton("📨 Мои вопросы", callback_data="my:questions"))
    return kb

def cancel_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ Отменить", callback_data="cancel"))
    return kb

def admin_menu_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("📂 Открытые", callback_data="adm:open"),
           types.InlineKeyboardButton("🔒 Закрытые", callback_data="adm:closed"))
    kb.add(types.InlineKeyboardButton("📋 Все заявки", callback_data="adm:tickets"),
           types.InlineKeyboardButton("💬 Вопросы", callback_data="adm:questions"))
    kb.add(types.InlineKeyboardButton("📊 Статистика", callback_data="adm:stats"),
           types.InlineKeyboardButton("🚫 Баны", callback_data="adm:bans"))
    kb.add(types.InlineKeyboardButton("📢 Рассылка", callback_data="adm:bc"),
           types.InlineKeyboardButton("📤 CSV", callback_data="adm:csv"))
    return kb

def ticket_list_kb(rows):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        label = f"{r['code']} {STATUS.get(r['status'],'')} — {r['target']}"
        kb.add(types.InlineKeyboardButton(label[:60], callback_data=f"t:{r['code']}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="adm:menu"))
    return kb

def closed_list_kb(rows):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        label = f"🔒 {r['code']} — {r['target']}"
        kb.add(types.InlineKeyboardButton(label[:60], callback_data=f"rc:{r['code']}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="adm:menu"))
    return kb

def ticket_card_kb(code, target_username="", is_closed=False):
    kb = types.InlineKeyboardMarkup(row_width=3)
    if is_closed:
        kb.add(types.InlineKeyboardButton("🔓 Открыть заново", callback_data=f"rc:{code}"))
        kb.add(types.InlineKeyboardButton("🗑 Удалить", callback_data=f"td:{code}"))
        uname = (target_username or "").lstrip("@").strip()
        if uname and all(c.isalnum() or c == "_" for c in uname):
            kb.add(types.InlineKeyboardButton(f"👤 Профиль @{uname}",
                url=f"https://t.me/{uname}"))
        kb.add(types.InlineKeyboardButton("⬅️ К списку", callback_data="adm:closed"))
        return kb
    kb.add(types.InlineKeyboardButton("💬 Ответить", callback_data=f"tr:{code}"),
           types.InlineKeyboardButton("🔧 В работу", callback_data=f"tw:{code}"),
           types.InlineKeyboardButton("✅ Выдать", callback_data=f"ti:{code}"))
    kb.add(types.InlineKeyboardButton("❌ Отказ", callback_data=f"tj:{code}"),
           types.InlineKeyboardButton("🚫 Бан", callback_data=f"tb:{code}"),
           types.InlineKeyboardButton("🗑 Удалить", callback_data=f"td:{code}"))
    kb.add(types.InlineKeyboardButton("🔒 Закрыть заявку", callback_data=f"tc:{code}"))
    uname = (target_username or "").lstrip("@").strip()
    if uname and all(c.isalnum() or c == "_" for c in uname):
        kb.add(types.InlineKeyboardButton(f"👤 Профиль @{uname}",
            url=f"https://t.me/{uname}"))
    kb.add(types.InlineKeyboardButton("⬅️ К списку", callback_data="adm:open"))
    return kb

def user_ticket_kb(code):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🔒 Закрыть заявку", callback_data=f"uc:{code}"))
    kb.add(types.InlineKeyboardButton("👁 Убрать из списка", callback_data=f"uh:{code}"))
    return kb

def user_my_list_kb(rows):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        label = f"{r['code']} {STATUS.get(r['status'],'')} — {r['text'][:25]}"
        kb.add(types.InlineKeyboardButton(label[:60], callback_data=f"uv:{r['code']}"))
    return kb

def question_list_kb(rows):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for r in rows:
        label = f"{r['code']} {QSTATUS.get(r['status'],'')} — @{r['username'] or '—'}"
        kb.add(types.InlineKeyboardButton(label[:60], callback_data=f"qv:{r['code']}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="adm:menu"))
    return kb

def question_card_kb(code):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("💬 Ответить", callback_data=f"qr:{code}"),
           types.InlineKeyboardButton("🔒 Закрыть", callback_data=f"qc:{code}"))
    kb.add(types.InlineKeyboardButton("⬅️ К списку", callback_data="adm:questions"))
    return kb

# ============ ФОРМАТ ============
def fmt_ticket(t):
    return (f"🎁 *Заявка {t['code']}*\n"
            f"Статус: {STATUS.get(t['status'], t['status'])}\n\n"
            f"👤 @{t['username'] or '—'} (`{t['user_id']}`)\n"
            f"🎯 Кому: {t['target']}\n\n"
            f"📝 {t['text']}\n\n"
            f"🕐 {time.strftime('%d.%m %H:%M', time.localtime(t['created']))}")

def fmt_user_ticket(t):
    return (f"🎁 *Заявка {t['code']}*\n"
            f"Статус: {STATUS.get(t['status'], t['status'])}\n\n"
            f"🎯 Кому: {t['target']}\n\n"
            f"📝 {t['text']}\n\n"
            f"🕐 {time.strftime('%d.%m %H:%M', time.localtime(t['created']))}")

def fmt_question(r):
    ans = f"\n\n✅ *Ответ:* {r['answer']}" if r["answer"] else ""
    return (f"💬 *Вопрос {r['code']}*\n"
            f"Статус: {QSTATUS.get(r['status'], r['status'])}\n\n"
            f"👤 @{r['username'] or '—'} (`{r['user_id']}`)\n\n"
            f"📝 {r['text']}{ans}\n\n"
            f"🕐 {time.strftime('%d.%m %H:%M', time.localtime(r['created']))}")

def is_banned(uid):
    return q("SELECT user_id FROM banned WHERE user_id=?", (uid,), one=True) is not None

# ============ КОМАНДЫ ============
@bot.message_handler(commands=["start"])
def h_start(m):
    if m.from_user.id == ADMIN_ID:
        return bot.send_message(m.chat.id, "👑 Админ. /menu — панель.",
                                reply_markup=admin_menu_kb())
    if is_banned(m.from_user.id):
        return bot.send_message(m.chat.id, "🚫 Забанен.")
    bot.send_message(m.chat.id,
        "👋 Привет! Это бот быстрых выдач NFT.\n\n"
        "🎁 Нажми «Подать заявку» — напиши что нужно и @username в конце.\n"
        "💬 Есть вопрос? Жми «Задать вопрос».",
        parse_mode="Markdown", reply_markup=main_kb())

@bot.message_handler(commands=["id"])
def h_id(m): bot.reply_to(m, f"`{m.from_user.id}`", parse_mode="Markdown")

@bot.message_handler(commands=["menu"])
def h_menu(m):
    if m.from_user.id != ADMIN_ID: return
    bot.send_message(m.chat.id, "🛠 Админ-меню:", reply_markup=admin_menu_kb())

@bot.message_handler(commands=["cancel"])
def h_cancel(m):
    if m.from_user.id in states:
        del states[m.from_user.id]
        return bot.send_message(m.chat.id, "Отменено.", reply_markup=main_kb())
    bot.send_message(m.chat.id, "Нечего отменять.")

@bot.message_handler(commands=["status"])
def h_status(m):
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return bot.send_message(m.chat.id, "Использование: `/status КОД`\nПример: `/status H1LD-SDEF`",
                                parse_mode="Markdown")
    code = parts[1].strip().upper()
    t = q("SELECT * FROM tickets WHERE code=? AND user_id=?", (code, m.from_user.id), one=True)
    if not t:
        return bot.send_message(m.chat.id, f"Заявка `{code}` не найдена.", parse_mode="Markdown")
    bot.send_message(m.chat.id, fmt_user_ticket(t), parse_mode="Markdown")

# ============ СТАРТ ЗАЯВКИ ============
@bot.callback_query_handler(func=lambda c: c.data == "n:new")
def cb_new_ticket(c):
    bot.answer_callback_query(c.id)
    uid = c.from_user.id
    if is_banned(uid): return bot.send_message(c.message.chat.id, "🚫 Забанен.")
    if int(time.time()) - cooldown.get(uid, 0) < COOLDOWN:
        return bot.send_message(c.message.chat.id, "⏳ Подожди.")
    states[uid] = {"kind": "nft"}
    bot.send_message(c.message.chat.id,
        "📝 Напиши ОДНО сообщение: что нужно + `@username` в конце.\n\n"
        "Пример:\n`2 NFT из коллекции X для дропа @nick`",
        parse_mode="Markdown", reply_markup=cancel_kb())

@bot.callback_query_handler(func=lambda c: c.data == "q:new")
def cb_new_question(c):
    bot.answer_callback_query(c.id)
    uid = c.from_user.id
    if is_banned(uid): return bot.send_message(c.message.chat.id, "🚫 Забанен.")
    if int(time.time()) - cooldown.get(uid, 0) < COOLDOWN:
        return bot.send_message(c.message.chat.id, "⏳ Подожди.")
    states[uid] = {"kind": "question"}
    bot.send_message(c.message.chat.id,
        "💬 Напиши свой вопрос:", reply_markup=cancel_kb())

@bot.callback_query_handler(func=lambda c: c.data == "cancel")
def cb_cancel(c):
    states.pop(c.from_user.id, None)
    bot.answer_callback_query(c.id, "Отменено")
    bot.send_message(c.message.chat.id, "Главное меню:", reply_markup=main_kb())

# ============ ЕДИНЫЙ ТЕКСТ ============
@bot.message_handler(content_types=["text"])
def h_all_text(m):
    uid = m.from_user.id
    txt = (m.text or "").strip()
    if txt.startswith("/"): return

    if uid == ADMIN_ID and ADMIN_ID in states:
        st = states.get(ADMIN_ID, {})
        kind = st.get("kind")
        if kind == "reply_ticket":
            code = st["code"]; del states[ADMIN_ID]
            t = q("SELECT * FROM tickets WHERE code=?", (code,), one=True)
            if not t: return bot.reply_to(m, "❌ Заявка не найдена")
            if t["status"] == "closed":
                return bot.reply_to(m, "🔒 Заявка закрыта — сначала открой заново")
            try:
                bot.send_message(t["chat_id"], f"💬 Ответ по заявке {code}:\n\n{txt}")
                bot.reply_to(m, "✅ Отправлено")
            except Exception as e:
                bot.reply_to(m, f"❌ Ошибка: {e}")
            return
        if kind == "reply_question":
            code = st["code"]; del states[ADMIN_ID]
            r = q("SELECT * FROM questions WHERE code=?", (code,), one=True)
            if not r: return bot.reply_to(m, "❌ Вопрос не найден")
            try:
                bot.send_message(r["chat_id"], f"💬 Ответ на вопрос {code}:\n\n{txt}")
                x("UPDATE questions SET answer=?, status='answered' WHERE code=?", (txt, code))
                bot.reply_to(m, "✅ Отправлено")
            except Exception as e:
                bot.reply_to(m, f"❌ Ошибка: {e}")
            return
        if kind == "bc":
            del states[ADMIN_ID]
            uids = set()
            for r in q("SELECT DISTINCT chat_id FROM tickets"): uids.add(r["chat_id"])
            for r in q("SELECT DISTINCT chat_id FROM questions"): uids.add(r["chat_id"])
            ok = 0
            for cid in uids:
                try: bot.send_message(cid, f"📢 {txt}"); ok += 1; time.sleep(0.05)
                except Exception: pass
            return bot.reply_to(m, f"📢 {ok}/{len(uids)}")
        del states[ADMIN_ID]
        return bot.send_message(m.chat.id, "Режим сброшен.", reply_markup=admin_menu_kb())

    if uid in states:
        st = states[uid]
        if st.get("kind") == "question":
            now = int(time.time()); code = gen_code()
            x("INSERT INTO questions(code,user_id,chat_id,username,text,created) VALUES(?,?,?,?,?,?)",
              (code, uid, m.chat.id, m.from_user.username or "", txt, now))
            del states[uid]; cooldown[uid] = now
            bot.send_message(m.chat.id, f"✅ Вопрос {code} отправлен.", reply_markup=main_kb())
            r = q("SELECT * FROM questions WHERE code=?", (code,), one=True)
            try:
                bot.send_message(ADMIN_ID, fmt_question(r), parse_mode="Markdown",
                                 reply_markup=question_card_kb(code))
            except Exception as e: print("[NOTIFY Q]", e)
            return
        if st.get("kind") == "nft":
            if "@" not in txt:
                return bot.send_message(m.chat.id,
                    "⚠️ В конце сообщения укажи `@username`.\nПример: `2 NFT @nick`",
                    parse_mode="Markdown")
            parts = txt.rsplit("@", 1)
            body = parts[0].strip()
            target = "@" + parts[1].split()[0].strip() if len(parts) > 1 else "—"
            if not body:
                return bot.send_message(m.chat.id, "⚠️ Добавь текст перед @username.")
            now = int(time.time()); code = gen_code()
            x("INSERT INTO tickets(code,user_id,chat_id,username,text,target,created) VALUES(?,?,?,?,?,?,?)",
              (code, uid, m.chat.id, m.from_user.username or "", body, target, now))
            del states[uid]; cooldown[uid] = now
            # автоответ
            bot.send_message(m.chat.id,
                f"✅ Заявка *{code}* принята.\n\n"
                f"⏳ Автоответ: администратор рассмотрит заявку до 24 часов.\n"
                f"Ответ придёт сюда же.\n\n"
                f"📋 Следи за статусом: `/status {code}`",
                parse_mode="Markdown", reply_markup=main_kb())
            t = q("SELECT * FROM tickets WHERE code=?", (code,), one=True)
            try:
                bot.send_message(ADMIN_ID, fmt_ticket(t), parse_mode="Markdown",
                                 reply_markup=ticket_card_kb(code, target, is_closed=False))
            except Exception as e: print("[NOTIFY T]", e)
            return

    if uid != ADMIN_ID:
        if is_banned(uid): return bot.send_message(m.chat.id, "🚫 Забанен.")
        return bot.send_message(m.chat.id, "Выбери действие:", reply_markup=main_kb())
    bot.send_message(m.chat.id, "Админ-меню:", reply_markup=admin_menu_kb())

# ============ МОИ ЗАЯВКИ (только открытые) ============
@bot.callback_query_handler(func=lambda c: c.data == "my:tickets")
def cb_my_tickets(c):
    bot.answer_callback_query(c.id)
    rows = q("SELECT * FROM tickets WHERE user_id=? AND hidden=0 AND status != 'closed' ORDER BY id DESC LIMIT 20",
             (c.from_user.id,))
    if not rows: return bot.send_message(c.message.chat.id, "Заявок нет.")
    bot.send_message(c.message.chat.id, "📋 Твои заявки:",
                     reply_markup=user_my_list_kb(rows))

@bot.callback_query_handler(func=lambda c: c.data.startswith("uv:") and c.data.count(":")==1)
def cb_user_view_ticket(c):
    code = c.data.split(":")[1]
    t = q("SELECT * FROM tickets WHERE code=? AND user_id=?", (code, c.from_user.id), one=True)
    if not t: return bot.answer_callback_query(c.id, "Не найдена", show_alert=True)
    if t["status"] == "closed":
        return bot.answer_callback_query(c.id, "🔒 Заявка закрыта", show_alert=True)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, fmt_user_ticket(t), parse_mode="Markdown",
                     reply_markup=user_ticket_kb(code))

@bot.callback_query_handler(func=lambda c: c.data.startswith("uc:") and c.data.count(":")==1)
def cb_user_close_ticket(c):
    code = c.data.split(":")[1]
    t = q("SELECT * FROM tickets WHERE code=? AND user_id=?", (code, c.from_user.id), one=True)
    if not t: return bot.answer_callback_query(c.id, "Не найдена", show_alert=True)
    if t["status"] == "closed":
        return bot.answer_callback_query(c.id, "Уже закрыта", show_alert=True)
    x("UPDATE tickets SET status='closed' WHERE code=?", (code,))
    bot.answer_callback_query(c.id, "Закрыто")
    bot.send_message(c.message.chat.id, f"🔒 Заявка *{code}* закрыта и убрана из списка.",
                     parse_mode="Markdown")
    try:
        bot.send_message(ADMIN_ID, f"🔒 @{t['username'] or '—'} закрыл заявку {code}")
    except Exception: pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("uh:") and c.data.count(":")==1)
def cb_user_hide_ticket(c):
    code = c.data.split(":")[1]
    t = q("SELECT * FROM tickets WHERE code=? AND user_id=?", (code, c.from_user.id), one=True)
    if not t: return bot.answer_callback_query(c.id, "Не найдена", show_alert=True)
    x("UPDATE tickets SET hidden=1 WHERE code=?", (code,))
    bot.answer_callback_query(c.id, "Убрано")
    bot.send_message(c.message.chat.id, f"👁 Заявка {code} убрана.")

# ============ МОИ ВОПРОСЫ ============
@bot.callback_query_handler(func=lambda c: c.data == "my:questions")
def cb_my_questions(c):
    bot.answer_callback_query(c.id)
    rows = q("SELECT * FROM questions WHERE user_id=? AND hidden=0 ORDER BY id DESC LIMIT 20",
             (c.from_user.id,))
    if not rows: return bot.send_message(c.message.chat.id, "Вопросов нет.")
    bot.send_message(c.message.chat.id, "📨 Твои вопросы:\n" + "\n".join(
        f"{r['code']} {QSTATUS.get(r['status'])} — {r['text'][:40]}" for r in rows))

# ============ АДМИН-МЕНЮ ============
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:"))
def cb_admin_menu(c):
    if c.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
    bot.answer_callback_query(c.id)
    k = c.data.split(":")[1]

    if k == "menu":
        return bot.send_message(c.message.chat.id, "🛠 Меню:", reply_markup=admin_menu_kb())
    if k == "open":
        rows = q("SELECT * FROM tickets WHERE status != 'closed' ORDER BY id DESC LIMIT 30")
        if not rows: return bot.send_message(c.message.chat.id, "Открытых заявок нет.")
        return bot.send_message(c.message.chat.id, "📂 Открытые:",
                                reply_markup=ticket_list_kb(rows))
    if k == "closed":
        rows = q("SELECT * FROM tickets WHERE status = 'closed' ORDER BY id DESC LIMIT 30")
        if not rows: return bot.send_message(c.message.chat.id, "Закрытых заявок нет.")
        return bot.send_message(c.message.chat.id, "🔒 Закрытые (нажми чтобы открыть заново):",
                                reply_markup=closed_list_kb(rows))
    if k == "stats":
        tot = q("SELECT COUNT(*) c FROM tickets", one=True)["c"]
        new = q("SELECT COUNT(*) c FROM tickets WHERE status='new'", one=True)["c"]
        work = q("SELECT COUNT(*) c FROM tickets WHERE status='in_work'", one=True)["c"]
        iss = q("SELECT COUNT(*) c FROM tickets WHERE status='issued'", one=True)["c"]
        clo = q("SELECT COUNT(*) c FROM tickets WHERE status='closed'", one=True)["c"]
        qs = q("SELECT COUNT(*) c FROM questions", one=True)["c"]
        qnew = q("SELECT COUNT(*) c FROM questions WHERE status='new'", one=True)["c"]
        return bot.send_message(c.message.chat.id,
            f"📊 *Статистика*\n\n"
            f"🎁 Заявки: {tot} (🆕 {new} | 🔧 {work} | ✅ {iss} | 🔒 {clo})\n"
            f"💬 Вопросы: {qs} (🆕 {qnew})", parse_mode="Markdown")
    if k == "tickets":
        rows = q("SELECT * FROM tickets ORDER BY id DESC LIMIT 30")
        if not rows: return bot.send_message(c.message.chat.id, "Заявок нет.")
        return bot.send_message(c.message.chat.id, "📋 Все заявки:",
                                reply_markup=ticket_list_kb(rows))
    if k == "questions":
        rows = q("SELECT * FROM questions ORDER BY id DESC LIMIT 30")
        if not rows: return bot.send_message(c.message.chat.id, "Вопросов нет.")
        return bot.send_message(c.message.chat.id, "💬 Вопросы:",
                                reply_markup=question_list_kb(rows))
    if k == "bans":
        rows = q("SELECT * FROM banned")
        if not rows: return bot.send_message(c.message.chat.id, "Пусто.")
        kb = types.InlineKeyboardMarkup(row_width=1)
        for r in rows:
            kb.add(types.InlineKeyboardButton(f"Разбан {r['user_id']}",
                callback_data=f"ub:{r['user_id']}"))
        return bot.send_message(c.message.chat.id, "🚫 Баны:", reply_markup=kb)
    if k == "bc":
        states[ADMIN_ID] = {"kind": "bc"}
        return bot.send_message(c.message.chat.id, "📢 Текст рассылки (или /cancel):")
    if k == "csv":
        path = f"tickets_{int(time.time())}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["code","user","username","text","target","status","created"])
            for r in q("SELECT * FROM tickets ORDER BY id"):
                w.writerow([r["code"], r["user_id"], r["username"], r["text"],
                            r["target"], r["status"],
                            time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created"]))])
        with open(path, "rb") as f:
            bot.send_document(c.message.chat.id, f)

# ============ ОТКРЫТИЕ ЗАЯВКИ (админ) ============
@bot.callback_query_handler(func=lambda c: c.data.startswith("t:") and c.data.count(":")==1)
def cb_open_ticket(c):
    if c.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
    parts = c.data.split(":")
    if len(parts) != 2:
        return bot.answer_callback_query(c.id, f"Битый формат: {c.data}", show_alert=True)
    code = parts[1]
    t = q("SELECT * FROM tickets WHERE code=?", (code,), one=True)
    if not t: return bot.answer_callback_query(c.id, f"Заявка {code} не в базе", show_alert=True)
    is_closed = (t["status"] == "closed")
    bot.answer_callback_query(c.id, f"Заявка {code}")
    bot.send_message(c.message.chat.id, fmt_ticket(t), parse_mode="Markdown",
                     reply_markup=ticket_card_kb(code, t["target"], is_closed))

# ============ ПЕРЕОТКРЫТЬ ЗАКРЫТУЮ ============
@bot.callback_query_handler(func=lambda c: c.data.startswith("rc:") and c.data.count(":")==1)
def cb_reopen_closed(c):
    if c.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
    code = c.data.split(":")[1]
    t = q("SELECT * FROM tickets WHERE code=?", (code,), one=True)
    if not t:
        return bot.answer_callback_query(c.id, "Заявка не найдена", show_alert=True)
    x("UPDATE tickets SET status='new', hidden=0 WHERE code=?", (code,))
    bot.answer_callback_query(c.id, "Открыта заново")
    bot.send_message(c.message.chat.id, f"🔓 Заявка {code} снова открыта (Новая).")
    try:
        bot.send_message(t["chat_id"], f"🔓 Твоя заявка {code} снова открыта.")
    except Exception: pass

# ============ ДЕЙСТВИЯ (админ) ============
@bot.callback_query_handler(func=lambda c: c.data[:2] in ("tr","tw","ti","tj","tb","td","tc") and ":" in c.data)
def cb_ticket_action(c):
    if c.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
    parts = c.data.split(":")
    if len(parts) != 2:
        return bot.answer_callback_query(c.id, f"Битый формат: {c.data}", show_alert=True)
    act, code = parts[0], parts[1]
    t = q("SELECT * FROM tickets WHERE code=?", (code,), one=True)
    if not t: return bot.answer_callback_query(c.id, f"Заявка {code} не в базе", show_alert=True)
    # защита закрытой заявки
    if t["status"] == "closed" and act != "td":
        return bot.answer_callback_query(c.id, "🔒 Заявка закрыта — сначала открой заново", show_alert=True)
    bot.answer_callback_query(c.id)

    if act == "tr":
        states[ADMIN_ID] = {"kind": "reply_ticket", "code": code}
        return bot.send_message(c.message.chat.id, f"✍️ Ответ по {code} (или /cancel):")
    if act == "tw":
        x("UPDATE tickets SET status='in_work' WHERE code=?", (code,))
        try: bot.send_message(t["chat_id"], f"🔧 Заявка {code} в работе.")
        except Exception: pass
        return bot.send_message(c.message.chat.id, f"🔧 {code} → в работе")
    if act == "ti":
        x("UPDATE tickets SET status='issued' WHERE code=?", (code,))
        try: bot.send_message(t["chat_id"], f"✅ Заявка {code} выдана!")
        except Exception: pass
        return bot.send_message(c.message.chat.id, f"✅ {code} → выдана")
    if act == "tj":
        x("UPDATE tickets SET status='rejected' WHERE code=?", (code,))
        try: bot.send_message(t["chat_id"], f"❌ Заявка {code} отклонена.")
        except Exception: pass
        return bot.send_message(c.message.chat.id, f"❌ {code} → отказ")
    if act == "tc":
        x("UPDATE tickets SET status='closed' WHERE code=?", (code,))
        try: bot.send_message(t["chat_id"], f"🔒 Заявка {code} закрыта и убрана из твоего списка.")
        except Exception: pass
        return bot.send_message(c.message.chat.id, f"🔒 {code} → закрыта")
    if act == "tb":
        x("INSERT OR REPLACE INTO banned(user_id,ts) VALUES(?,?)",
          (t["user_id"], int(time.time())))
        return bot.send_message(c.message.chat.id, f"🚫 @{t['username']} забанен")
    if act == "td":
        x("DELETE FROM tickets WHERE code=?", (code,))
        return bot.send_message(c.message.chat.id, f"🗑 {code} удалена")

# ============ ВОПРОСЫ (админ) ============
@bot.callback_query_handler(func=lambda c: c.data.startswith("qv:"))
def cb_open_question(c):
    if c.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
    parts = c.data.split(":")
    if len(parts) != 2:
        return bot.answer_callback_query(c.id, f"Битый: {c.data}", show_alert=True)
    code = parts[1]
    r = q("SELECT * FROM questions WHERE code=?", (code,), one=True)
    if not r: return bot.answer_callback_query(c.id, f"Вопрос {code} не в базе", show_alert=True)
    bot.answer_callback_query(c.id)
    bot.send_message(c.message.chat.id, fmt_question(r), parse_mode="Markdown",
                     reply_markup=question_card_kb(code))

@bot.callback_query_handler(func=lambda c: c.data[:2] in ("qr","qc") and ":" in c.data)
def cb_question_action(c):
    if c.from_user.id != ADMIN_ID:
        return bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
    parts = c.data.split(":")
    if len(parts) != 2:
        return bot.answer_callback_query(c.id, f"Битый: {c.data}", show_alert=True)
    act, code = parts[0], parts[1]
    r = q("SELECT * FROM questions WHERE code=?", (code,), one=True)
    if not r: return bot.answer_callback_query(c.id, f"Вопрос {code} не в базе", show_alert=True)
    bot.answer_callback_query(c.id)
    if act == "qr":
        states[ADMIN_ID] = {"kind": "reply_question", "code": code}
        return bot.send_message(c.message.chat.id, f"✍️ Ответ на {code} (или /cancel):")
    if act == "qc":
        x("UPDATE questions SET status='closed' WHERE code=?", (code,))
        return bot.send_message(c.message.chat.id, f"🔒 Вопрос {code} закрыт")

@bot.callback_query_handler(func=lambda c: c.data.startswith("ub:"))
def cb_unban(c):
    if c.from_user.id != ADMIN_ID: return
    uid = int(c.data.split(":")[1])
    x("DELETE FROM banned WHERE user_id=?", (uid,))
    bot.answer_callback_query(c.id, "Разбанен")
    try: bot.edit_message_text(f"✅ Разбан {uid}", c.message.chat.id, c.message.message_id)
    except Exception: pass

# ============ ЗАПУСК ============
if __name__ == "__main__":
    print("Снимаю webhook...")
    try:
        bot.delete_webhook(drop_pending_updates=False)
    except Exception as e:
        print("⚠️ webhook:", e)

    while True:
        try:
            me = bot.get_me()
            print(f"✅ Запуск @{me.username}")
            break
        except Exception as e:
            print(f"⏳ Сервер недоступен: {str(e)[:120]}")
            print("   Жду 15 сек...")
            time.sleep(15)

    print(f"ADMIN_ID = {ADMIN_ID}")
    cnt = q("SELECT COUNT(*) c FROM tickets", one=True)["c"]
    qcnt = q("SELECT COUNT(*) c FROM questions", one=True)["c"]
    print(f"📊 В базе: заявок={cnt}, вопросов={qcnt}")

    while True:
        try:
            bot.infinity_polling(allowed_updates=["message","callback_query"],
                                 timeout=30, long_polling_timeout=30)
        except Exception as e:
            print(f"⚠️ Polling упал: {e}")
            print("   Перезапуск через 10 сек...")
            time.sleep(10)