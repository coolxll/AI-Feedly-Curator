"""Interactive Feedly stream selection for the terminal client."""

from rss_analyzer.feedly_client import (
    feedly_get_categories,
    feedly_get_subscriptions,
    feedly_get_unread_counts,
)


GLOBAL_STREAM_SENTINEL = "__GLOBAL_ALL__"


def select_stream_interactive(
    *,
    console,
    get_categories=feedly_get_categories,
    get_subscriptions=feedly_get_subscriptions,
    get_unread_counts=feedly_get_unread_counts,
):
    """Interactive stream selector"""
    import questionary

    console.print("[dim]正在获取 Feedly 目录与未读统计...[/dim]")

    # Parallel fetch could be better but sequential is safer for now
    categories = get_categories()
    subscriptions = get_subscriptions()
    counts_data = get_unread_counts()

    if not categories or not subscriptions or not counts_data:
        console.print("[red]获取 Feedly 目录信息失败。[/red]")
        if questionary.confirm(
            "是否继续使用默认全局所有订阅 (Global Stream)?", default=True
        ).ask():
            return None, "Global (Default)"
        return None, None

    # Map counts
    # API returns: {"unreadcounts": [{"id": "...", "count": 123, "updated": ...}]}
    count_map = {
        item["id"]: item["count"] for item in counts_data.get("unreadcounts", [])
    }

    # Create ID to Label mapping for return value
    id_to_label = {}

    choices = []

    # 1. Global All
    global_count = 0
    for cid, count in count_map.items():
        if "global.all" in cid:
            global_count = count
            break

    global_label = f"🌐 全局所有订阅 (Global All, 共 {global_count} 篇未读)"
    choices.append(questionary.Choice(global_label, value=GLOBAL_STREAM_SENTINEL))
    id_to_label[GLOBAL_STREAM_SENTINEL] = "Global All"

    # 2. Categories
    cat_choices = []
    for cat in categories:
        cid = cat["id"]
        label = cat["label"]
        count = count_map.get(cid, 0)
        if count > 0:
            display_label = f"📁 分类: {label}"
            cat_choices.append((count, display_label, cid))
            id_to_label[cid] = f"Category: {label}"

    # Sort by count descending
    cat_choices.sort(key=lambda x: x[0], reverse=True)

    for count, label, cid in cat_choices:
        choices.append(questionary.Choice(f"{label} ({count} 篇未读)", value=cid))

    # 3. Feeds (Top 20 by unread count)
    feed_choices = []
    for sub in subscriptions:
        fid = sub["id"]
        title = sub["title"]
        count = count_map.get(fid, 0)
        if count > 0:
            display_label = f"📰 订阅源: {title}"
            feed_choices.append((count, display_label, fid))
            id_to_label[fid] = f"Feed: {title}"

    feed_choices.sort(key=lambda x: x[0], reverse=True)

    # Add separator if we have feeds
    if feed_choices:
        choices.append(questionary.Separator("--- 📰 订阅源 (Feeds) ---"))

    for i, (count, label, fid) in enumerate(feed_choices):
        if i >= 50:  # Limit to top 50 to avoid clutter
            break
        choices.append(questionary.Choice(f"{label} ({count} 篇未读)", value=fid))

    choices.append(questionary.Separator("--- ⚙️ 其他 (Other) ---"))
    choices.append(questionary.Choice("✍️ 手动输入 Stream ID (Manual ID)", value="MANUAL"))

    stream_id = questionary.select(
        "请选择要处理的订阅源或分类 (Select Stream):",
        choices=choices,
        style=questionary.Style(
            [
                ("qmark", "fg:cyan bold"),
                ("question", "fg:cyan bold"),
                ("answer", "fg:green bold"),
                ("pointer", "fg:cyan bold"),
                ("highlighted", "fg:cyan bold"),
                ("selected", "fg:green bold"),
            ]
        ),
    ).ask()

    stream_label = None
    if stream_id == GLOBAL_STREAM_SENTINEL:
        return None, "Global All"

    if stream_id == "MANUAL":
        stream_id = questionary.text("请输入 Stream ID:").ask()
        if not stream_id:
            return None, None
        stream_label = f"Manual ID: {stream_id}"
    else:
        stream_label = id_to_label.get(stream_id, str(stream_id))

    return stream_id, stream_label
