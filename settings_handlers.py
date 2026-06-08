import logging
import os
import signal
import html
import asyncio
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters,
)
from price_history import get_stats_7d, get_trend, get_median_7d

logger = logging.getLogger(__name__)


def _reply_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("⚙️ Меню"), KeyboardButton("🔎 Проверка")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def _main_menu_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Поиски", callback_data="m:list"),
         InlineKeyboardButton("➕ Добавить", callback_data="m:add")],
        [InlineKeyboardButton("🔎 Проверка", callback_data="m:actual")],
        [InlineKeyboardButton("💰 Мин. цены", callback_data="m:prices"),
         InlineKeyboardButton("📊 Статистика", callback_data="m:stats")],
        [InlineKeyboardButton("🚫 Стоп-слова", callback_data="m:filters"),
         InlineKeyboardButton("⚙️ Настройки", callback_data="m:settings")],
        [InlineKeyboardButton("❌ Закрыть", callback_data="m:close")],
    ])


def _main_menu_text(config):
    searches = config.get_searches()
    groups = _search_groups(searches)
    return (
        f"⚙️ <b>eBay Monitor</b>\n\n"
        f"🔍 <b>{len(groups)}</b> товаров · <b>{len(searches)}</b> вариантов"
    )


def _set_return(context, callback, label):
    context.user_data["_ret_cb"] = callback
    context.user_data["_ret_lbl"] = label


def _get_return_markup(context, fallback_cb="m:main", fallback_lbl="🔙 Назад"):
    cb = context.user_data.pop("_ret_cb", fallback_cb)
    lbl = context.user_data.pop("_ret_lbl", fallback_lbl)
    keyboard = [[InlineKeyboardButton(lbl, callback_data=cb)]]
    if cb != "m:main":
        keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")])
    return InlineKeyboardMarkup(keyboard)


def _make_progress_bar(done, total, width=12):
    total = max(total, 1)
    done = max(0, min(done, total))
    pct = int(done / total * 100)
    filled = min(width, int(round(done / total * width)))
    return ("▰" * filled) + ("▱" * (width - filled)), pct


EBAY_CATEGORIES = [
    ("all", "🌍 Все категории"),
    ("phones", "📱 Смартфоны"),
    ("electronics", "🔌 Электроника"),
    ("computers", "💻 Компьютеры/планшеты"),
    ("laptops", "💻 Ноутбуки"),
    ("monitors", "🖥 Мониторы"),
    ("mice", "🖱 Мыши"),
    ("headphones", "🎧 Наушники"),
    ("vr", "🥽 Virtual Reality"),
    ("vr_headsets", "🥽 VR-шлемы"),
    ("consoles", "🎮 Консоли"),
    ("tablets", "📲 Планшеты"),
    ("phone_parts", "🔧 Запчасти телефонов"),
    ("phone_accessories", "🧩 Аксессуары/чехлы"),
    ("smart_watches", "⌚ Смарт-часы"),
    ("cameras", "📷 Камеры"),
    ("video_games", "🎮 Игры/консоли"),
]


COND_LABELS = {"used": "Б/у", "new": "Новый", "any": "Любое"}
LISTING_LABELS = {"buy_now": "Купить сейчас", "buy_now_offer": "Купить сейчас + торг", "auction": "Аукцион", "offer": "Предложить цену", "all": "Все"}
SELLER_LABELS = {"private": "Частники", "any": "Все"}
LOCATION_LABELS = {"de": "🇩🇪 Германия", "eu": "🇪🇺 Европа", "worldwide": "🌍 Весь мир"}


def _price_label(filters):
    min_price = filters.get("min_price")
    max_price = filters.get("max_price")
    if min_price is not None and max_price is not None:
        return f"{min_price}–{max_price}€"
    if min_price is not None:
        return f"≥{min_price}€"
    if max_price is not None:
        return f"≤{max_price}€"
    return "без лимита"


def _category_label(value):
    labels = dict(EBAY_CATEGORIES)
    return labels.get(value or "all", str(value or "all"))


def _query_key(query):
    return " ".join(str(query or "").casefold().split())


def _search_groups(searches):
    groups = []
    by_key = {}
    for search in searches:
        key = _query_key(search.get("query"))
        if not key:
            key = search.get("id", "")
        group = by_key.get(key)
        if group is None:
            group = {
                "key": key,
                "query": search.get("query", key),
                "category": search.get("filters", {}).get("category") or "all",
                "items": [],
            }
            by_key[key] = group
            groups.append(group)
        cat = search.get("filters", {}).get("category") or "all"
        if group["category"] == "all" and cat != "all":
            group["category"] = cat
        group["items"].append(search)
    return groups


def _groups_by_category(searches):
    groups = {}
    for group in _search_groups(searches):
        groups.setdefault(group["category"], []).append(group)
    order = [cat for cat in groups if cat != "all"]
    if "all" in groups:
        order.append("all")
    return groups, order


def _group_for_search_id(searches, search_id):
    current = next((s for s in searches if s.get("id") == search_id), None)
    if not current:
        return None
    key = _query_key(current.get("query"))
    return next((g for g in _search_groups(searches) if g["key"] == key), None)


def _listing_icon(value):
    return {
        "buy_now_offer": "🛒",
        "buy_now": "🛒",
        "auction": "🔨",
        "offer": "💬",
        "all": "🔎",
    }.get(value or "all", "🔎")


def _variant_label(search):
    filters = search.get("filters", {})
    listing = filters.get("listing_type", "all")
    listing_names = {
        "buy_now_offer": "Купить+торг",
        "buy_now": "Купить",
        "auction": "Аукцион",
        "offer": "Торг",
        "all": "Все",
    }
    parts = [listing_names.get(listing, LISTING_LABELS.get(listing, listing))]
    price = _price_label(filters)
    if price != "без лимита":
        parts.append(price)
    condition = filters.get("condition")
    if condition and condition != "any":
        parts.append(COND_LABELS.get(condition, condition))
    return f"{_listing_icon(listing)} " + " · ".join(parts)


def _words_total(group, field):
    return sum(len(search.get(field, [])) for search in group["items"])


def _category_keyboard(prefix="aw:cat", back_cb="m:main"):
    rows = []
    for i in range(0, len(EBAY_CATEGORIES), 2):
        row = []
        for key, label in EBAY_CATEGORIES[i:i + 2]:
            row.append(InlineKeyboardButton(label, callback_data=f"{prefix}:{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data=back_cb)])
    return InlineKeyboardMarkup(rows)


def _short_item_url(item):
    url = item.get("url", "") or ""
    item_id = item.get("item_id", "")
    host = "www.ebay.com"
    m = re.search(r"https?://([^/]+)/itm/(\d+)", url)
    if m:
        host = m.group(1)
        item_id = m.group(2)
    if item_id:
        return f"https://{host}/itm/{item_id}"
    return url


def _fit_html_lines(lines, limit=3900):
    result = []
    total = 0
    for line in lines:
        extra = len(line) + 1
        if total + extra > limit:
            result.append("...")
            break
        result.append(line)
        total += extra
    return "\n".join(result)


def _word_list_content(search, search_id, kind, done_cb=None):
    is_exclude = kind == "exclude"
    field = "exclude_words" if is_exclude else "include_words"
    title = "🚫 <b>Исключения</b>" if is_exclude else "✅ <b>Обязательные слова</b>"
    words = list(search.get(field, [])) if search else []
    query = html.escape(search.get("query", search_id)) if search else html.escape(search_id)
    lines = [f"{title} · <b>{query}</b>\n"]
    if words:
        lines.extend(f"• <code>{html.escape(w)}</code>" for w in words)
    else:
        lines.append("Пусто.")
    lines.append("\nНапиши слово сообщением, чтобы добавить.")

    remove_prefix = "exc_rm" if is_exclude else "inc_rm"
    clear_prefix = "exc_clear" if is_exclude else "inc_clear"
    rows = []
    row = []
    for word in words[:20]:
        row.append(InlineKeyboardButton(f"❌ {word[:18]}", callback_data=f"{remove_prefix}:{search_id}:{word}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if words:
        rows.append([InlineKeyboardButton("🗑 Очистить все", callback_data=f"{clear_prefix}:{search_id}")])
    rows.append([
        InlineKeyboardButton("✅ Готово", callback_data=done_cb or f"s:{search_id}"),
        InlineKeyboardButton("✏️ Редактировать", callback_data=f"se:{search_id}"),
    ])
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def register_settings_handlers(app: Application, config):

    async def _show_main(target, context, is_new_msg=False):
        text = _main_menu_text(config)
        markup = _main_menu_markup()
        if is_new_msg:
            await target.reply_text(text, parse_mode="HTML", reply_markup=markup)
        else:
            await target.edit_text(text, parse_mode="HTML", reply_markup=markup)

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("👋", reply_markup=_reply_keyboard())
        await _show_main(update.message, context, is_new_msg=True)

    async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        searches = config.get_searches()
        if not searches:
            await update.message.reply_text("Нет поисков. Нажми 📋 Меню → ➕ Добавить", reply_markup=_reply_keyboard())
            return
        groups = _search_groups(searches)
        buttons = [[InlineKeyboardButton(f"🔎 {g['query']} ({len(g['items'])})", callback_data=f"ag:{g['items'][0]['id']}")] for g in groups]
        buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")])
        await update.message.reply_text(
            "🔎 <b>Проверка</b>\n\nВыбери поиск:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def keyboard_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()
        ud = context.user_data
        logger.info("text from %s: %r", update.effective_user.id if update.effective_user else "?", text)

        if text in ("Меню", "⚙️ Меню", "📋 Меню", "⚙️ Настройки", "Настройки"):
            await _show_main(update.message, context, is_new_msg=True)
            return
        if "Проверка" in text or "Актуальные" in text:
            searches = config.get_searches()
            if not searches:
                await update.message.reply_text("Нет поисков. Открой меню → Добавить поиск")
                return
            groups = _search_groups(searches)
            buttons = [[InlineKeyboardButton(f"🔎 {g['query']} ({len(g['items'])})", callback_data=f"ag:{g['items'][0]['id']}")] for g in groups]
            buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")])
            await update.message.reply_text(
                "🔎 <b>Проверка</b>\n\nВыбери поиск:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            return

        if ud.get("add_step") == "query":
            ud["add_data"]["query"] = text
            ud["add_step"] = "category"
            await update.message.reply_text(
                "🧭 <b>Категория eBay</b>\n\n"
                "Для телефона лучше выбрать <b>📱 Смартфоны</b>, чтобы не ловить чехлы.",
                parse_mode="HTML",
                reply_markup=_category_keyboard(),
            )
            return
        if ud.get("add_step") == "price":
            if text.lower() in ("нет", "no", "-", "0"):
                ud["add_data"].setdefault("filters", {})["max_price"] = None
            else:
                try:
                    ud["add_data"].setdefault("filters", {})["max_price"] = int(text)
                except ValueError:
                    await update.message.reply_text("❌ Число или 'нет'")
                    return
            ud["add_step"] = "condition"
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Б/у", callback_data="aw:cond:used"),
                    InlineKeyboardButton("Новый", callback_data="aw:cond:new"),
                    InlineKeyboardButton("Любое", callback_data="aw:cond:any"),
                ],
                [InlineKeyboardButton("❌ Отмена", callback_data="m:main")],
            ])
            await update.message.reply_text("📦 Состояние:", reply_markup=keyboard)
            return
        if ud.get("add_step") == "exclude":
            word = text.strip().lower()
            if word:
                ud["add_data"].setdefault("exclude_words", []).append(word)
            current = ud["add_data"].get("exclude_words", [])
            await update.message.reply_text(
                f"🚫 Исключения: {', '.join(current)}\n\nВведи ещё слово или нажми Готово",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Готово", callback_data="aw:exc_done")],
                    [InlineKeyboardButton("❌ Отмена", callback_data="m:main")],
                ]),
            )
            return

        if ud.get("edit_query_id"):
            sid = ud["edit_query_id"]
            new_query = text.strip()
            if not new_query:
                await update.message.reply_text("❌ Пустой запрос нельзя сохранить")
                return
            ud.pop("edit_query_id", None)
            config.update_search(sid, {"query": new_query})
            await update.message.reply_text(
                f"✅ Запрос: <b>{html.escape(new_query)}</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ Редактировать", callback_data=f"se:{sid}")],
                    [InlineKeyboardButton("🔙 К поиску", callback_data=f"s:{sid}")],
                ]),
            )
            return

        if ud.get("edit_price_id"):
            sid = ud["edit_price_id"]
            raw = text.strip().lower()
            if raw in ("нет", "no", "-", "0", "без", "none"):
                price = None
            else:
                try:
                    price = int(float(raw.replace(",", ".")))
                except ValueError:
                    await update.message.reply_text("❌ Введи число в € или 'нет'")
                    return
            ud.pop("edit_price_id", None)
            config.update_search(sid, {"filters": {"max_price": price}})
            label = f"{price}€" if price else "без лимита"
            await update.message.reply_text(
                f"✅ Макс. цена: <b>{label}</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ Редактировать", callback_data=f"se:{sid}")],
                    [InlineKeyboardButton("Назад к поиску", callback_data=f"s:{sid}")],
                ]),
            )
            return

        if ud.get("edit_exclude_id"):
            sid = ud["edit_exclude_id"]
            s = config.get_search_by_id(sid)
            current = list(s.get("exclude_words", [])) if s else []
            word = text.strip().lower()
            if word in ("очистить", "clear"):
                config.update_search(sid, {"exclude_words": []})
                s = config.get_search_by_id(sid)
                body, markup = _word_list_content(s, sid, "exclude", ud.get("_ret_cb"))
                await update.message.reply_text(body, parse_mode="HTML", reply_markup=markup)
                return
            if word and word not in current:
                current.append(word)
                config.update_search(sid, {"exclude_words": current})
            s = config.get_search_by_id(sid)
            body, markup = _word_list_content(s, sid, "exclude", ud.get("_ret_cb"))
            await update.message.reply_text(body, parse_mode="HTML", reply_markup=markup)
            return
        if ud.get("edit_include_id"):
            sid = ud["edit_include_id"]
            s = config.get_search_by_id(sid)
            current = list(s.get("include_words", [])) if s else []
            word = text.strip().lower()
            if word in ("очистить", "clear"):
                config.update_search(sid, {"include_words": []})
                s = config.get_search_by_id(sid)
                body, markup = _word_list_content(s, sid, "include", ud.get("_ret_cb"))
                await update.message.reply_text(body, parse_mode="HTML", reply_markup=markup)
                return
            if word and word not in current:
                current.append(word)
                config.update_search(sid, {"include_words": current})
            s = config.get_search_by_id(sid)
            body, markup = _word_list_content(s, sid, "include", ud.get("_ret_cb"))
            await update.message.reply_text(body, parse_mode="HTML", reply_markup=markup)
            return
        if ud.get("set_zip"):
            ud.pop("set_zip")
            config.update_settings({"user_zip": text})
            await update.message.reply_text(f"✅ ZIP: {text}", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Настройки", callback_data="m:settings")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")],
            ]))
            return
        if ud.get("set_tax"):
            ud.pop("set_tax")
            try:
                val = float(text)
                config.update_settings({"non_eu_tax_rate": val})
                await update.message.reply_text(f"✅ НДС: {val*100:.0f}%", reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Настройки", callback_data="m:settings")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")],
                ]))
            except ValueError:
                await update.message.reply_text("❌ Число (например 0.19)")
            return

    async def inline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        msg = query.message

        if data.startswith("hide:"):
            item_id = data[5:]
            config.ban_item(item_id)
            from monitor import seen_ids, save_seen_ids
            seen_ids.add(item_id)
            save_seen_ids()
            await query.answer("❌ Объявление скрыто")
            try:
                # Replace the message caption/text with "СКРЫТО" marker
                if msg.caption:
                    # Photo message — edit caption
                    short = msg.caption.split("\n")[0] if msg.caption else ""
                    await msg.edit_caption(
                        caption=f"❌ <s>{short}</s>\n\n<i>Скрыто</i>",
                        parse_mode="HTML",
                        reply_markup=None,
                    )
                elif msg.text:
                    short = msg.text.split("\n")[0] if msg.text else ""
                    await msg.edit_text(
                        text=f"❌ <s>{short}</s>\n\n<i>Скрыто</i>",
                        parse_mode="HTML",
                        reply_markup=None,
                    )
                else:
                    await msg.edit_reply_markup(reply_markup=None)
            except Exception:
                try:
                    await msg.edit_reply_markup(reply_markup=None)
                except Exception:
                    pass
            return

        if data.startswith("mcs:"):
            try:
                idx = int(data[4:])
            except ValueError:
                await query.answer("Ошибка")
                return
            cache = context.user_data.get("mc_cache") or []
            if idx < 0 or idx >= len(cache):
                await query.answer("Устарело — обнови проверку", show_alert=True)
                return
            item = cache[idx]
            sid = context.user_data.get("mc_search_id")
            search = config.get_search_by_id(sid) if sid else None
            from monitor import send_notification
            try:
                await send_notification(context.bot, item, search or {"id": sid, "query": ""})
                await query.answer("📤 Отправлено")
            except Exception as e:
                logger.error("mcs send error: %s", e)
                await query.answer("Ошибка отправки", show_alert=True)
            return

        if data.startswith("ban:"):
            seller = data[4:]
            config.ban_seller_global(seller)
            from price_history import delete_seller_data
            delete_seller_data(seller)
            await query.answer(f"🚫 Продавец {seller} забанен")
            try:
                if msg.caption:
                    short = msg.caption.split("\n")[0] if msg.caption else ""
                    await msg.edit_caption(
                        caption=f"🚫 <s>{short}</s>\n\n<i>Продавец {html.escape(seller)} забанен</i>",
                        parse_mode="HTML",
                        reply_markup=None,
                    )
                elif msg.text:
                    short = msg.text.split("\n")[0] if msg.text else ""
                    await msg.edit_text(
                        text=f"🚫 <s>{short}</s>\n\n<i>Продавец {html.escape(seller)} забанен</i>",
                        parse_mode="HTML",
                        reply_markup=None,
                    )
                else:
                    await msg.edit_reply_markup(reply_markup=None)
            except Exception:
                try:
                    await msg.edit_reply_markup(reply_markup=None)
                except Exception:
                    pass
            return

        if data == "m:main":
            for key in (
                "add_step", "add_data", "edit_exclude_id", "edit_include_id",
                "edit_query_id", "edit_price_id", "set_zip", "set_tax",
                "_ret_cb", "_ret_lbl",
            ):
                context.user_data.pop(key, None)
            await _show_main(msg, context)

        elif data == "m:close":
            try:
                await msg.delete()
            except Exception:
                await msg.edit_text("✅")

        elif data == "noop":
            pass

        elif data == "m:list":
            await _show_search_list(msg, context)

        elif data.startswith("cat:"):
            category = data[4:]
            await _show_category_searches(msg, context, category)

        elif data.startswith("sg:"):
            search_id = data[3:]
            await _show_search_group(msg, context, search_id)

        elif data == "m:add":
            context.user_data["add_step"] = "query"
            context.user_data["add_data"] = {}
            await msg.edit_text("🔍 Введи поисковый запрос:", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("❌ Отмена", callback_data="m:main")]]
            ))

        elif data == "m:stats":
            await _show_stats(msg, context)

        elif data == "m:prices":
            await _show_min_prices(msg, context)

        elif data == "m:settings":
            await _show_settings(msg, context)

        elif data == "m:toggle_mode":
            from monitor import _is_statistics_mode, _sync_mode_to_github
            current = _is_statistics_mode(config)
            new_val = not current
            config.update_settings({"test_summary_mode": new_val})
            
            # Write to mode.txt
            try:
                mode_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mode.txt')
                with open(mode_file, 'w', encoding='utf-8') as f:
                    f.write('statistics' if new_val else 'normal')
            except Exception as e:
                logger.error(f"Failed to write mode.txt: {e}")
                
            mode_str = "Статистика" if new_val else "Обычный"
            await query.answer(f"⚙️ Режим изменен на: {mode_str} (сохранение в GitHub...)", show_alert=False)
            
            # Run sync in background task
            async def do_sync_bg():
                try:
                    await asyncio.to_thread(_sync_mode_to_github)
                except Exception as e:
                    logger.error(f"Auto-sync failed on toggle: {e}")
            asyncio.create_task(do_sync_bg())
            
            await _show_settings(msg, context)

        elif data == "m:filters":
            await _show_filters_menu(msg, context)

        elif data.startswith("fcat:"):
            category = data[5:]
            await _show_filter_category(msg, context, category)

        elif data.startswith("fg:"):
            search_id = data[3:]
            await _show_filter_group(msg, context, search_id)

        elif data == "m:actual":
            await _show_actual_select(msg, context)

        elif data.startswith("ag:"):
            search_id = data[3:]
            await _show_actual_group(msg, context, search_id)

        elif data.startswith("s:"):
            search_id = data[2:]
            await _show_search_detail(msg, context, search_id)

        elif data.startswith("se:"):
            search_id = data[3:]
            await _show_search_edit(msg, context, search_id)

        elif data.startswith("seq:"):
            search_id = data[4:]
            context.user_data["edit_query_id"] = search_id
            await msg.edit_text(
                "🔍 Введи новый поисковый запрос:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Назад к редактированию", callback_data=f"se:{search_id}")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")],
                ]),
            )

        elif data.startswith("seprice:"):
            search_id = data[8:]
            context.user_data["edit_price_id"] = search_id
            await msg.edit_text(
                "Введи максимальную цену в € или <code>нет</code>:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Редактировать", callback_data=f"se:{search_id}")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")],
                ]),
            )

        elif data.startswith("secat:"):
            search_id = data[6:]
            await msg.edit_text(
                "🧭 <b>Категория eBay</b>",
                parse_mode="HTML",
                reply_markup=_category_keyboard(prefix=f"catset:{search_id}", back_cb=f"se:{search_id}"),
            )

        elif data.startswith("ef:"):
            _, search_id, field = data.split(":", 2)
            await _show_filter_choice(msg, context, search_id, field)

        elif data.startswith("efs:"):
            _, search_id, field, value = data.split(":", 3)
            config.update_search(search_id, {"filters": {field: value}})
            await _show_search_edit(msg, context, search_id)

        elif data.startswith("qc:"):
            search_id = data[3:]
            s = config.get_search_by_id(search_id)
            if s:
                await _do_market_check(msg, context, s)

        elif data.startswith("del:"):
            search_id = data[4:]
            await _confirm_delete(msg, context, search_id)

        elif data.startswith("del_yes:"):
            search_id = data[8:]
            config.delete_search(search_id)
            await msg.edit_text("🗑 Удалён", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 К поискам", callback_data="m:list")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")],
            ]))

        elif data.startswith("exc:"):
            search_id = data[4:]
            context.user_data["edit_exclude_id"] = search_id
            _set_return(context, f"s:{search_id}", "🔙 К поиску")
            await _show_word_list(msg, context, search_id, "exclude")

        elif data.startswith("inc:"):
            search_id = data[4:]
            context.user_data["edit_include_id"] = search_id
            _set_return(context, f"s:{search_id}", "🔙 К поиску")
            await _show_word_list(msg, context, search_id, "include")

        elif data.startswith("fexc:"):
            search_id = data[5:]
            context.user_data["edit_exclude_id"] = search_id
            _set_return(context, f"fg:{search_id}", "🔙 К фильтрам")
            await _show_word_list(msg, context, search_id, "exclude")

        elif data.startswith("finc:"):
            search_id = data[5:]
            context.user_data["edit_include_id"] = search_id
            _set_return(context, f"fg:{search_id}", "🔙 К фильтрам")
            await _show_word_list(msg, context, search_id, "include")

        elif data == "set:zip":
            context.user_data["set_zip"] = True
            await msg.edit_text(
                "📍 Введи свой ZIP-код (например 09648):",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Настройки", callback_data="m:settings")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")],
                ]),
            )

        elif data == "set:tax":
            context.user_data["set_tax"] = True
            await msg.edit_text(
                "💶 Введи ставку НДС для не-ЕС (например 0.19):",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Настройки", callback_data="m:settings")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")],
                ]),
            )

        elif data.startswith("catpick:"):
            search_id = data[8:]
            await msg.edit_text(
                "🧭 <b>Категория eBay</b>\n\n"
                "Для телефона выбери <b>📱 Смартфоны</b>, чтобы отсечь чехлы и аксессуары.",
                parse_mode="HTML",
                reply_markup=_category_keyboard(prefix=f"catset:{search_id}", back_cb=f"s:{search_id}"),
            )

        elif data.startswith("catset:"):
            _, search_id, category = data.split(":", 2)
            config.update_search(search_id, {"filters": {"category": category}})
            await query.answer(f"Категория: {_category_label(category)}")
            await _show_search_edit(msg, context, search_id)

        elif data.startswith("aw:cat:"):
            category = data[7:]
            context.user_data["add_data"].setdefault("filters", {})["category"] = category
            context.user_data["add_step"] = "price"
            await msg.edit_text(
                f"🧭 Категория: <b>{html.escape(_category_label(category))}</b>\n\n"
                "💰 Макс. цена в €? (или 'нет')",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="m:main")]]),
            )

        elif data.startswith("aw:cond:"):
            cond = data[8:]
            context.user_data["add_data"].setdefault("filters", {})["condition"] = cond
            context.user_data["add_step"] = "listing"
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Купить+торг", callback_data="aw:lt:buy_now_offer"),
                    InlineKeyboardButton("Аукцион", callback_data="aw:lt:auction"),
                ],
                [
                    InlineKeyboardButton("Купить сейчас", callback_data="aw:lt:buy_now"),
                    InlineKeyboardButton("Предложить цену", callback_data="aw:lt:offer"),
                ],
                [InlineKeyboardButton("Все", callback_data="aw:lt:all")],
                [InlineKeyboardButton("❌ Отмена", callback_data="m:main")],
            ])
            await msg.edit_text("🛒 Формат покупки:", reply_markup=keyboard)

        elif data.startswith("aw:lt:"):
            lt = data[6:]
            context.user_data["add_data"].setdefault("filters", {})["listing_type"] = lt
            context.user_data["add_step"] = "seller_type"
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Только частники", callback_data="aw:st:private"),
                    InlineKeyboardButton("Все продавцы", callback_data="aw:st:any"),
                ],
                [InlineKeyboardButton("❌ Отмена", callback_data="m:main")],
            ])
            await msg.edit_text("👤 Тип продавца:", reply_markup=keyboard)

        elif data.startswith("aw:st:"):
            st = data[6:]
            context.user_data["add_data"].setdefault("filters", {})["seller_type"] = st
            context.user_data["add_step"] = "location"
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🇩🇪 Германия", callback_data="aw:loc:de"),
                    InlineKeyboardButton("🇪🇺 Европа", callback_data="aw:loc:eu"),
                    InlineKeyboardButton("🌍 Везде", callback_data="aw:loc:worldwide"),
                ],
                [InlineKeyboardButton("❌ Отмена", callback_data="m:main")],
            ])
            await msg.edit_text("🌍 Откуда:", reply_markup=keyboard)

        elif data.startswith("aw:loc:"):
            loc = data[7:]
            context.user_data["add_data"].setdefault("filters", {})["location"] = loc
            context.user_data["add_step"] = "exclude"
            await msg.edit_text(
                "🚫 Введи слово для исключения (Enter — следующее)",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⏭ Пропустить", callback_data="aw:skip_exc")],
                    [InlineKeyboardButton("❌ Отмена", callback_data="m:main")],
                ]),
            )

        elif data == "aw:exc_done":
            search = config.add_search(context.user_data.get("add_data", {}))
            context.user_data.pop("add_step", None)
            context.user_data.pop("add_data", None)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔎 Проверка", callback_data=f"qc:{search['id']}")],
                [InlineKeyboardButton("📋 К поискам", callback_data="m:list")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")],
            ])
            await msg.edit_text(f"✅ Поиск <b>{html.escape(search['query'])}</b> добавлен!", parse_mode="HTML", reply_markup=keyboard)

        elif data == "aw:skip_exc":
            context.user_data["add_data"]["exclude_words"] = []
            search = config.add_search(context.user_data["add_data"])
            context.user_data.pop("add_step", None)
            context.user_data.pop("add_data", None)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔎 Проверка", callback_data=f"qc:{search['id']}")],
                [InlineKeyboardButton("📋 К поискам", callback_data="m:list")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")],
            ])
            await msg.edit_text(f"✅ Поиск <b>{html.escape(search['query'])}</b> добавлен!", parse_mode="HTML", reply_markup=keyboard)

        elif data.startswith("exc_clear:"):
            sid = data[10:]
            config.update_search(sid, {"exclude_words": []})
            context.user_data["edit_exclude_id"] = sid
            await _show_word_list(msg, context, sid, "exclude")

        elif data.startswith("inc_clear:"):
            sid = data[10:]
            config.update_search(sid, {"include_words": []})
            context.user_data["edit_include_id"] = sid
            await _show_word_list(msg, context, sid, "include")

        elif data.startswith("exc_rm:"):
            parts = data[7:].split(":", 1)
            sid, word = parts[0], parts[1] if len(parts) > 1 else ""
            s = config.get_search_by_id(sid)
            if s:
                words = [w for w in s.get("exclude_words", []) if w != word]
                config.update_search(sid, {"exclude_words": words})
            context.user_data["edit_exclude_id"] = sid
            await _show_word_list(msg, context, sid, "exclude")

        elif data.startswith("inc_rm:"):
            parts = data[7:].split(":", 1)
            sid, word = parts[0], parts[1] if len(parts) > 1 else ""
            s = config.get_search_by_id(sid)
            if s:
                words = [w for w in s.get("include_words", []) if w != word]
                config.update_search(sid, {"include_words": words})
            context.user_data["edit_include_id"] = sid
            await _show_word_list(msg, context, sid, "include")

    async def _show_search_list(msg, context):
        searches = config.get_searches()
        if not searches:
            text = "📋 <b>Поиски</b>\n\nСписок пуст."
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить", callback_data="m:add")],
                [InlineKeyboardButton("🔙 Назад", callback_data="m:main")],
            ])
        else:
            grouped, cat_order = _groups_by_category(searches)
            total_groups = sum(len(items) for items in grouped.values())
            lines = [f"📋 <b>Поиски</b> · {total_groups} товаров / {len(searches)} вариантов"]
            buttons = []
            for cat in cat_order:
                items = grouped[cat]
                cat_label = _category_label(cat)
                lines.append(f"\n{cat_label} · {len(items)}")
                for group in items[:3]:
                    lines.append(f"  🔍 {html.escape(group['query'])} · {len(group['items'])} вар.")
                if len(items) > 3:
                    lines.append(f"  … ещё {len(items) - 3}")
                buttons.append([InlineKeyboardButton(
                    f"{cat_label} ({len(items)})",
                    callback_data=f"cat:{cat}"
                )])
            buttons.append([
                InlineKeyboardButton("➕ Добавить", callback_data="m:add"),
                InlineKeyboardButton("🔙 Назад", callback_data="m:main"),
            ])
            keyboard = InlineKeyboardMarkup(buttons)
            text = "\n".join(lines)
        try:
            await msg.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            pass

    async def _show_category_searches(msg, context, category):
        grouped, _ = _groups_by_category(config.get_searches())
        searches = grouped.get(category, [])
        cat_label = _category_label(category)
        if not searches:
            await msg.edit_text(f"{cat_label}\n\nНет поисков.", parse_mode="HTML",
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("🔙 К поискам", callback_data="m:list")]]))
            return
        lines = [f"{cat_label} · {len(searches)}"]
        buttons = []
        for group in searches:
            first_id = group["items"][0]["id"]
            buttons.append([InlineKeyboardButton(
                f"🔍 {group['query']} ({len(group['items'])})",
                callback_data=f"sg:{first_id}",
            )])
        buttons.append([InlineKeyboardButton("🔙 К поискам", callback_data="m:list")])
        await msg.edit_text("\n".join(lines), parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup(buttons))

    async def _show_search_group(msg, context, search_id):
        for key in ("edit_exclude_id", "edit_include_id", "edit_query_id", "edit_price_id"):
            context.user_data.pop(key, None)
        group = _group_for_search_id(config.get_searches(), search_id)
        if not group:
            await msg.edit_text("❌ Не найден", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 К поискам", callback_data="m:list")]]))
            return
        lines = [
            f"🔍 <b>{html.escape(group['query'])}</b>",
            f"🧭 {_category_label(group['category'])}",
            f"⚙️ Вариантов: <b>{len(group['items'])}</b>",
        ]
        buttons = [
            [InlineKeyboardButton(_variant_label(item), callback_data=f"s:{item['id']}")]
            for item in group["items"]
        ]
        buttons.append([
            InlineKeyboardButton("🔙 Категория", callback_data=f"cat:{group['category']}"),
            InlineKeyboardButton("📋 Все", callback_data="m:list"),
        ])
        await msg.edit_text("\n".join(lines), parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup(buttons))

    async def _show_filters_menu(msg, context):
        searches = config.get_searches()
        banned_s = config.get_global_banned_sellers()
        banned_i = config.get_banned_item_ids()
        grouped, cat_order = _groups_by_category(searches)
        total_groups = sum(len(items) for items in grouped.values())
        
        # Count total exclude/include words
        total_exc = sum(len(s.get("exclude_words", [])) for s in searches)
        total_inc = sum(len(s.get("include_words", [])) for s in searches)
        
        lines = [
            "🚫 <b>Стоп-слова и бан-лист</b>\n",
            "Бот НЕ покажет объявление если:",
            "• В названии есть <b>стоп-слово</b> (настраивается для каждого поиска)",
            "• Продавец в <b>бан-листе</b> (глобально для всех поисков)",
            "• Объявление скрыто вручную\n",
            f"📝 Стоп-слов: <b>{total_exc}</b> · обязательных: <b>{total_inc}</b>",
            f"🚷 Бан: <b>{len(banned_s)}</b> продавцов · <b>{len(banned_i)}</b> объявлений\n",
            "Выбери категорию для настройки стоп-слов:",
        ]
        buttons = [
            [InlineKeyboardButton(f"{_category_label(cat)} ({len(grouped[cat])})", callback_data=f"fcat:{cat}")]
            for cat in cat_order
        ]
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="m:main")])
        await msg.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

    async def _show_filter_category(msg, context, category):
        grouped, _ = _groups_by_category(config.get_searches())
        groups = grouped.get(category, [])
        cat_label = _category_label(category)
        buttons = []
        for group in groups:
            first_id = group["items"][0]["id"]
            exc = _words_total(group, "exclude_words")
            inc = _words_total(group, "include_words")
            buttons.append([InlineKeyboardButton(
                f"🔍 {group['query']} · 🚫{exc} ✅{inc}",
                callback_data=f"fg:{first_id}",
            )])
        buttons.append([InlineKeyboardButton("🔙 Фильтры", callback_data="m:filters")])
        await msg.edit_text(f"🚫 <b>Фильтры</b>\n{cat_label}", parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup(buttons))

    async def _show_filter_group(msg, context, search_id):
        for key in ("edit_exclude_id", "edit_include_id", "edit_query_id", "edit_price_id"):
            context.user_data.pop(key, None)
        group = _group_for_search_id(config.get_searches(), search_id)
        if not group:
            await msg.edit_text("❌ Не найден", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Фильтры", callback_data="m:filters")]]))
            return
        lines = [
            "🚫 <b>Фильтры</b>",
            f"🔍 <b>{html.escape(group['query'])}</b>",
            f"⚙️ Вариантов: <b>{len(group['items'])}</b>",
        ]
        buttons = []
        for item in group["items"]:
            label = _variant_label(item)
            buttons.append([
                InlineKeyboardButton(f"🚫 {label} ({len(item.get('exclude_words', []))})", callback_data=f"fexc:{item['id']}"),
                InlineKeyboardButton(f"✅ {label} ({len(item.get('include_words', []))})", callback_data=f"finc:{item['id']}"),
            ])
        buttons.append([
            InlineKeyboardButton("🔙 Категория", callback_data=f"fcat:{group['category']}"),
            InlineKeyboardButton("🏠 Меню", callback_data="m:main"),
        ])
        await msg.edit_text("\n".join(lines), parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup(buttons))

    async def _show_actual_select(msg, context):
        searches = config.get_searches()
        if not searches:
            await msg.edit_text(
                "🔎 <b>Проверка</b>\n\nНет поисков.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Добавить", callback_data="m:add")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="m:main")],
                ]),
            )
            return
        groups = _search_groups(searches)
        buttons = []
        for g in groups:
            first_id = g["items"][0]["id"]
            buttons.append([InlineKeyboardButton(f"🔍 {g['query']}", callback_data=f"qc:{first_id}")])
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="m:main")])
        await msg.edit_text(
            "🔎 <b>Проверка</b>\nНажми — бот сразу покажет результаты:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def _show_actual_group(msg, context, search_id):
        group = _group_for_search_id(config.get_searches(), search_id)
        if not group:
            await msg.edit_text("❌ Не найден", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Проверка", callback_data="m:actual")]]))
            return
        buttons = [
            [InlineKeyboardButton(_variant_label(item), callback_data=f"qc:{item['id']}")]
            for item in group["items"]
        ]
        buttons.append([InlineKeyboardButton("🔙 Проверка", callback_data="m:actual")])
        await msg.edit_text(
            f"🔎 <b>{html.escape(group['query'])}</b>\n\nВыбери вариант:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    async def _show_search_detail(msg, context, search_id):
        context.user_data.pop("edit_exclude_id", None)
        context.user_data.pop("edit_include_id", None)
        context.user_data.pop("edit_query_id", None)
        context.user_data.pop("edit_price_id", None)
        s = config.get_search_by_id(search_id)
        if not s:
            await msg.edit_text("❌ Не найден", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 К поискам", callback_data="m:list")]]))
            return
        f = s.get("filters", {})
        exc = s.get("exclude_words", [])
        inc = s.get("include_words", [])
        price = _price_label(f)
        lines = [
            f"🔍 <b>{html.escape(s['query'])}</b>",
            "",
            f"💰 Цена: <b>{price}</b>",
            f"🚫 Исключения: <b>{len(exc)}</b> · ✅ Обязательные: <b>{len(inc)}</b>",
        ]
        banned_s = config.get_global_banned_sellers()
        banned_i = config.get_banned_item_ids()
        if banned_s or banned_i:
            lines.append(f"\n<i>🚷 Бан: {len(banned_s)} прод · {len(banned_i)} объяв</i>")

        buttons = [
            [InlineKeyboardButton("🔎 Проверить сейчас", callback_data=f"qc:{search_id}")],
            [
                InlineKeyboardButton(f"🚫 Искл ({len(exc)})", callback_data=f"exc:{search_id}"),
                InlineKeyboardButton(f"✅ Обяз ({len(inc)})", callback_data=f"inc:{search_id}"),
            ],
            [InlineKeyboardButton("✏️ Редактировать", callback_data=f"se:{search_id}")],
        ]
        buttons.append([
            InlineKeyboardButton("🗑 Удалить", callback_data=f"del:{search_id}"),
            InlineKeyboardButton("🔙 К товару", callback_data=f"sg:{search_id}"),
        ])
        await msg.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

    async def _show_word_list(msg, context, search_id, kind):
        s = config.get_search_by_id(search_id)
        if not s:
            await msg.edit_text("❌ Не найден", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 К поискам", callback_data="m:list")]]))
            return
        body, markup = _word_list_content(s, search_id, kind, context.user_data.get("_ret_cb"))
        await msg.edit_text(body, parse_mode="HTML", reply_markup=markup)

    async def _show_search_edit(msg, context, search_id):
        for key in ("edit_exclude_id", "edit_include_id", "edit_query_id", "edit_price_id"):
            context.user_data.pop(key, None)
        s = config.get_search_by_id(search_id)
        if not s:
            await msg.edit_text("❌ Не найден", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 К поискам", callback_data="m:list")]]))
            return
        f = s.get("filters", {})
        price = _price_label(f)
        lines = [
            f"✏️ <b>Редактировать</b>",
            f"🔍 <b>{html.escape(s['query'])}</b>",
            "",
            f"💰 Цена: <b>{price}</b>",
            f"🧭 Категория: {_category_label(f.get('category', 'all'))}",
            f"📦 Состояние: {COND_LABELS.get(f.get('condition', 'any'), f.get('condition', 'any'))}",
            f"🛍 Формат: {LISTING_LABELS.get(f.get('listing_type', 'all'), f.get('listing_type', 'all'))}",
            f"👤 Продавец: {SELLER_LABELS.get(f.get('seller_type', 'any'), f.get('seller_type', 'any'))}",
            f"🌍 Откуда: {LOCATION_LABELS.get(f.get('location', 'de'), f.get('location', 'de'))}",
        ]
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Запрос", callback_data=f"seq:{search_id}"),
             InlineKeyboardButton("💰 Цена", callback_data=f"seprice:{search_id}")],
            [InlineKeyboardButton("🧭 Категория", callback_data=f"secat:{search_id}")],
            [InlineKeyboardButton("Состояние", callback_data=f"ef:{search_id}:condition"),
             InlineKeyboardButton("Формат", callback_data=f"ef:{search_id}:listing_type")],
            [InlineKeyboardButton("Продавец", callback_data=f"ef:{search_id}:seller_type"),
             InlineKeyboardButton("🌍 Откуда", callback_data=f"ef:{search_id}:location")],
            [InlineKeyboardButton("🔙 К поиску", callback_data=f"s:{search_id}")],
        ])
        await msg.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)

    async def _show_filter_choice(msg, context, search_id, field):
        options = {
            "condition": [("used", "Б/у"), ("new", "Новый"), ("any", "Любое")],
            "listing_type": [("buy_now_offer", "Купить сейчас + торг"), ("buy_now", "Купить сейчас"), ("auction", "Аукцион"), ("offer", "Предложить цену"), ("all", "Все")],
            "seller_type": [("private", "Только частники"), ("any", "Все продавцы")],
            "location": [("de", "🇩🇪 Германия"), ("eu", "🇪🇺 Европа"), ("worldwide", "🌍 Везде")],
        }.get(field)
        if not options:
            await _show_search_edit(msg, context, search_id)
            return
        titles = {
            "condition": "📦 Состояние",
            "listing_type": "🛍 Формат покупки",
            "seller_type": "👤 Тип продавца",
            "location": "🌍 Откуда",
        }
        rows = []
        for i in range(0, len(options), 2):
            rows.append([
                InlineKeyboardButton(label, callback_data=f"efs:{search_id}:{field}:{value}")
                for value, label in options[i:i + 2]
            ])
        rows.append([InlineKeyboardButton("🔙 Редактировать", callback_data=f"se:{search_id}")])
        await msg.edit_text(
            f"{titles.get(field, 'Фильтр')}:",
            reply_markup=InlineKeyboardMarkup(rows),
        )

    async def _confirm_delete(msg, context, search_id):
        s = config.get_search_by_id(search_id)
        name = html.escape(s["query"]) if s else search_id
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Да, удалить", callback_data=f"del_yes:{search_id}"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"s:{search_id}"),
            ],
        ])
        await msg.edit_text(f"🗑 Удалить поиск <b>{name}</b>?", parse_mode="HTML", reply_markup=keyboard)

    async def _show_stats(msg, context):
        """Статистика — средние цены за месяц: Sofortkauf и Аукционы."""
        searches = config.get_searches()
        if not searches:
            await msg.edit_text("📊 Нет данных", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Меню", callback_data="m:main")]]))
            return
        
        groups = _search_groups(searches)
        lines = ["📊 <b>Статистика (30 дней)</b>\n"]
        
        # Buy now section
        lines.append("<b>🛒 Sofortkauf / Preisvorschlag:</b>")
        has_buy = False
        for group in groups:
            buy_variant = next(
                (s for s in group["items"] if "buy" in s.get("filters", {}).get("listing_type", "")),
                group["items"][0]
            )
            trend = get_trend(buy_variant["id"])
            stats = get_stats_7d(buy_variant["id"])
            if not stats and not trend:
                continue
            
            median = stats.get("median") if stats else None
            if not median and trend:
                median = trend.get("price_now")
            if not median:
                continue
            
            arrow = ""
            if trend:
                diff = trend["price_now"] - trend["price_30d_ago"]
                if diff < -20:
                    arrow = " 📉"
                elif diff > 20:
                    arrow = " 📈"
            
            lines.append(f"{group['query']}: <b>~{median:.0f}€</b>{arrow}")
            has_buy = True
        
        if not has_buy:
            lines.append("<i>Нет данных</i>")
        
        # Auction section
        lines.append("\n<b>🔨 Аукционы (ставки):</b>")
        has_auc = False
        for group in groups:
            auc_variant = next(
                (s for s in group["items"] if s.get("id", "").endswith("_auc")),
                None
            )
            if not auc_variant:
                continue
            stats = get_stats_7d(auc_variant["id"])
            if not stats:
                continue
            median = stats.get("median")
            if not median:
                continue
            lines.append(f"{group['query']}: <b>~{median:.0f}€</b>")
            has_auc = True
        
        if not has_auc:
            lines.append("<i>Нет данных</i>")
        
        lines.append("\n<i>📈 выросло за месяц · 📉 упало</i>")
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить", callback_data="m:stats"),
             InlineKeyboardButton("🔙 Назад", callback_data="m:main")],
        ])
        await msg.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)

    async def _show_min_prices(msg, context):
        """Мин. цены — текущий минимум по каждому товару."""
        searches = config.get_searches()
        if not searches:
            await msg.edit_text("💰 Нет данных", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Меню", callback_data="m:main")]]))
            return
        
        groups = _search_groups(searches)
        lines = ["💰 <b>Минимальные цены сейчас</b>\n"]
        
        for group in groups:
            buy_variant = next(
                (s for s in group["items"] if "buy" in s.get("filters", {}).get("listing_type", "")),
                group["items"][0]
            )
            stats = get_stats_7d(buy_variant["id"])
            if not stats:
                continue
            
            min_s = stats.get("min_sofort")
            median = stats.get("median")
            
            if min_s:
                deal = ""
                if median and min_s < median * 0.8:
                    deal = " 🔥"
                lines.append(f"{group['query']}: <b>{min_s:.0f}€</b>{deal}")
            elif median:
                lines.append(f"{group['query']}: ~{median:.0f}€")
        
        if len(lines) == 1:
            lines.append("<i>Бот собирает данные, подожди 1-2 дня.</i>")
        else:
            lines.append("\n<i>🔥 = сильно ниже медианы</i>")
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить", callback_data="m:prices"),
             InlineKeyboardButton("🔙 Назад", callback_data="m:main")],
        ])
        await msg.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)

    async def _show_settings(msg, context):
        st = config.get_settings()
        banned = config.get_global_banned_sellers()
        lines = ["⚙️ <b>Настройки</b>\n"]
        lines.append(f"📍 ZIP: <b>{st.get('user_zip') or 'не задан'}</b>")
        lines.append(f"🌍 Страна: {st.get('user_country', 'de')}")
        lines.append(f"💶 НДС не-ЕС: {st.get('non_eu_tax_rate', 0.19)*100:.0f}%")
        
        from monitor import _is_statistics_mode
        test_summary_mode = _is_statistics_mode(config)
        mode_str = "Статистика" if test_summary_mode else "Обычный"
        lines.append(f"📊 Автомониторинг: <b>{mode_str}</b>")

        if banned:
            lines.append(f"\n🚫 <b>Забаненные продавцы</b> ({len(banned)})")
            for b in banned[:10]:
                lines.append(f"  · {html.escape(b)}")
            if len(banned) > 10:
                lines.append(f"  … ещё {len(banned)-10}")

        mode_label = "📊 Автомониторинг: Статистика" if test_summary_mode else "🔄 Автомониторинг: Обычный"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📍 ZIP", callback_data="set:zip"),
             InlineKeyboardButton("💶 НДС", callback_data="set:tax")],
            [InlineKeyboardButton(mode_label, callback_data="m:toggle_mode")],
            [InlineKeyboardButton("🔙 Назад", callback_data="m:main")],
        ])
        await msg.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=keyboard)

    async def _do_market_check(msg, context, search, is_new_msg=False):
        from monitor import build_ebay_url, fetch_ebay_ex, filter_results, _seller_trust, _trust_emoji
        bar, pct = _make_progress_bar(1, 4)
        loading_text = (
            f"🔎 <b>Проверка eBay</b>\n\n"
            f"📱 Запрос: <b>{html.escape(search['query'])}</b>\n"
            f"{bar} {pct}%\n"
            f"📍 Этап: подключаюсь к eBay..."
        )
        if is_new_msg:
            sent = await msg.reply_text(loading_text, parse_mode="HTML")
        else:
            await msg.edit_text(loading_text, parse_mode="HTML")
            sent = msg

        results, fetch_err = await asyncio.to_thread(fetch_ebay_ex, search)
        sid = search["id"]
        q_html = html.escape(search['query'])
        ebay_url = build_ebay_url(search)

        if fetch_err:
            cooldown_msg = "🧊 <b>eBay временно блокирует наш IP.</b>\n"
            try:
                from monitor import _ebay_block_until
                import time as _t
                left = max(0, int(_ebay_block_until - _t.time()))
                if left > 0:
                    cooldown_msg += f"Бот сам подождёт ~{left // 60} мин {left % 60} сек, прежде чем повторно дёргать eBay.\n"
            except Exception:
                pass
            cooldown_msg += "Пока API-аккаунт не получил доступ, лучше открыть поиск вручную через кнопку ниже."
            err_msg = {
                "rate_limit": "🚦 <b>eBay ограничил частоту запросов (429).</b>\nБот сделал паузу, чтобы не усиливать блокировку. Пока можно открыть поиск вручную.",
                "blocked":    "🛑 <b>eBay заблокировал запрос</b> (captcha / антибот).\nБот не будет обходить captcha. Пока API-аккаунт ждёт доступ, открой поиск вручную.",
                "cooldown":   cooldown_msg,
                "api_not_configured": "🔑 <b>eBay API не настроен.</b>\nДобавь <code>EBAY_CLIENT_ID</code> и <code>EBAY_CLIENT_SECRET</code> в локальный env и GitHub Secrets.",
                "api_auth":   "🔐 <b>eBay API пока не даёт доступ.</b>\nЕсли аккаунт создан сегодня, это нормально: дождись одобрения eBay Developers. Ключи и marketplace тоже стоит проверить.",
                "api_rate_limit": "🚦 <b>eBay API ограничил частоту запросов.</b>\nПодожди и попробуй позже.",
                "network":    "📡 <b>Нет связи с eBay.</b>\nПроверь интернет и обнови.",
                "api_network": "📡 <b>Нет связи с eBay API.</b>\nПроверь интернет и попробуй позже.",
                "parse":      "⚠️ <b>Не удалось разобрать ответ eBay.</b>\nВозможно изменилась вёрстка.",
            }.get(fetch_err, f"⚠️ <b>Ошибка:</b> <code>{html.escape(fetch_err)}</code>")
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 Открыть eBay", url=ebay_url)],
                [InlineKeyboardButton("🔄 Повторить", callback_data=f"qc:{sid}"),
                 InlineKeyboardButton("🔙 К поиску", callback_data=f"s:{sid}")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")],
            ])
            await sent.edit_text(
                f"<b>{q_html}</b>\n\n{err_msg}",
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
            return

        bar, pct = _make_progress_bar(2, 4)
        await sent.edit_text(
            f"🔎 <b>Проверка eBay</b>\n\n"
            f"📱 Запрос: <b>{q_html}</b>\n"
            f"{bar} {pct}%\n"
            f"📦 eBay вернул: <b>{len(results)}</b>\n"
            f"📍 Этап: применяю фильтры...",
            parse_mode="HTML",
        )
        filtered = filter_results(results, search, config, skip_seen=True)
        filtered_new = filter_results(results, search, config, skip_seen=False)

        if not filtered:
            raw_count = len(results)
            if raw_count == 0:
                detail = (
                    "🔍 На eBay <b>вообще ни одного объявления</b> по этому запросу.\n"
                    "<i>(не «новых», а вообще)</i>\n\n"
                    "Возможные причины:\n"
                    "• Слишком узкие фильтры (цена, состояние, локация)\n"
                    "• Опечатка в запросе\n"
                    "• eBay временно скрыл результаты"
                )
            elif search.get("filters", {}).get("category") == "phones":
                detail = (
                    f"📦 eBay вернул <b>{raw_count}</b> объявл., но это не телефоны "
                    f"(чехлы / стекла / запчасти / нерелевантные товары).\n\n"
                    "Бот не показывает такой мусор. Можно открыть eBay вручную и проверить выдачу глазами."
                )
            else:
                detail = (
                    f"📦 eBay вернул <b>{raw_count}</b> объявл., но все отсеяны "
                    f"локальными фильтрами (стоп-слова / бан-лист / обяз. слова)."
                )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 Открыть eBay", url=ebay_url)],
                [InlineKeyboardButton("🔄 Обновить", callback_data=f"qc:{sid}"),
                 InlineKeyboardButton("🔙 К поиску", callback_data=f"s:{sid}")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")],
            ])
            await sent.edit_text(
                f"<b>{q_html}</b> — 0 результатов\n\n{detail}",
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
            return

        bar, pct = _make_progress_bar(3, 4)
        await sent.edit_text(
            f"🔎 <b>Проверка eBay</b>\n\n"
            f"📱 Запрос: <b>{q_html}</b>\n"
            f"{bar} {pct}%\n"
            f"📦 Найдено: <b>{len(results)}</b>\n"
            f"✅ После фильтров: <b>{len(filtered)}</b>\n"
            f"🆕 Новых: <b>{len(filtered_new)}</b>\n"
            f"📍 Этап: собираю карточку...",
            parse_mode="HTML",
        )
        sofort = sorted([r for r in filtered if r["buy_now"]], key=lambda x: x["total_price"])
        pv = sorted([r for r in filtered if r["best_offer"]], key=lambda x: x["total_price"])
        auctions = sorted([r for r in filtered if r["auction"]], key=lambda x: x["total_price"])

        f = search.get("filters", {})
        parts = []
        if f.get("category") and f.get("category") != "all":
            parts.append(_category_label(f.get("category")))
        cond_map = {"used": "б/у", "new": "новые", "any": "все"}
        if f.get("condition"):
            parts.append(cond_map.get(f["condition"], f["condition"]))
        if f.get("max_price"):
            parts.append(f"&lt;{f['max_price']}€")
        loc_map = {"de": "🇩🇪", "eu": "🇪🇺", "worldwide": "🌍"}
        parts.append(loc_map.get(f.get("location", "de"), ""))
        info = ", ".join(parts)

        now = datetime.now().strftime("%H:%M")
        bar, pct = _make_progress_bar(4, 4)
        lines = [
            f"📱 <b>{html.escape(search['query'])}</b> ({info})",
            f"🕐 {now}",
            f"{bar} {pct}%",
            f"📦 eBay: <b>{len(results)}</b> · после фильтров: <b>{len(filtered)}</b> · новых: <b>{len(filtered_new)}</b>\n",
        ]

        # Flat cache: index -> item, used for "📤 send" buttons
        cache = []
        def _push(item):
            cache.append(item)
            return len(cache) - 1

        def _line(idx, r, with_pv_mark=False, with_time=False):
            trust = _seller_trust(r["seller_rating_count"], r["seller_rating_percent"], r.get("top_rated"))
            emoji = _trust_emoji(trust)
            name = html.escape(r["seller_name"][:18]) if r["seller_name"] else "?"
            rc = r["seller_rating_count"]
            extra = " 🤝" if (with_pv_mark and r.get("best_offer")) else ""
            if with_time and r.get("time_left"):
                extra += f" — ⏰ {r['time_left']}"
            url = _short_item_url(r)
            label = f"{idx}. {r['price']:.0f}€"
            link = f'<a href="{html.escape(url)}">{label}</a>' if url else label
            return f"{link} {emoji} {name} ({rc}){extra}"

        send_rows = []  # rows of [📤 N] buttons grouped per category

        if sofort:
            lines.append(f"💰 <b>Купить сейчас ({len(sofort)}):</b>")
            row = []
            for i, r in enumerate(sofort[:5], 1):
                cidx = _push(r)
                lines.append(_line(i, r, with_pv_mark=True))
                row.append(InlineKeyboardButton(f"📤 {i}", callback_data=f"mcs:{cidx}"))
            if len(sofort) > 5:
                lines.append(f"   ⬇️ ещё {len(sofort)-5} от {sofort[5]['price']:.0f}€")
            send_rows.append(row)
            lines.append("")

        if pv:
            lines.append(f"🤝 <b>С предложением цены ({len(pv)}):</b>")
            row = []
            for i, r in enumerate(pv[:5], 1):
                cidx = _push(r)
                lines.append(_line(i, r))
                row.append(InlineKeyboardButton(f"📤 {i}", callback_data=f"mcs:{cidx}"))
            if len(pv) > 5:
                lines.append(f"   ⬇️ ещё {len(pv)-5}")
            send_rows.append(row)
            lines.append("")

        if auctions:
            lines.append(f"🔨 <b>Аукцион ({len(auctions)}):</b>")
            row = []
            for i, r in enumerate(auctions[:5], 1):
                cidx = _push(r)
                lines.append(_line(i, r, with_time=True))
                row.append(InlineKeyboardButton(f"📤 {i}", callback_data=f"mcs:{cidx}"))
            send_rows.append(row)
            lines.append("")

        trend = get_trend(sid)
        if trend and trend.get("price_30d_ago") and trend.get("price_now"):
            d = trend["price_now"] - trend["price_30d_ago"]
            pct = (d / trend["price_30d_ago"]) * 100 if trend["price_30d_ago"] else 0
            arrow = "↑" if d > 0 else "↓"
            lines.append(f"📈 Тренд: {trend['price_30d_ago']:.0f}€ → {trend['price_now']:.0f}€ ({arrow}{abs(pct):.0f}%)")

        # Save cache for "send" callback
        context.user_data["mc_cache"] = cache
        context.user_data["mc_search_id"] = sid

        text = _fit_html_lines(lines)

        kb_rows = list(send_rows)
        kb_rows.append([
            InlineKeyboardButton("🔄 Обновить", callback_data=f"qc:{sid}"),
            InlineKeyboardButton("🔙 К поиску", callback_data=f"s:{sid}"),
        ])
        kb_rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="m:main")])
        keyboard = InlineKeyboardMarkup(kb_rows)
        try:
            await sent.edit_text(text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)
        except Exception as e:
            logger.error("market check final render error: %s", e)
            safe_text = re.sub(r"<[^>]+>", "", text)
            await sent.edit_text(safe_text, reply_markup=keyboard, disable_web_page_preview=True)

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("menu", start_cmd))
    app.add_handler(CommandHandler("check", check_cmd))
    app.add_handler(CommandHandler("add", lambda u, c: keyboard_text(Update(u.update_id, message=u.message), c)))
    app.add_handler(CallbackQueryHandler(inline_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, keyboard_text))
