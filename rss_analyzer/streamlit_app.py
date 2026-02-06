import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
from datetime import datetime
import os

# 设置页面配置
st.set_page_config(
    page_title="RSS 文章分析仪表板",
    page_icon="📰",
    layout="wide"
)

def init_connection():
    """初始化数据库连接"""
    db_path = os.getenv("RSS_SCORES_DB", "rss_scores.db")
    return sqlite3.connect(db_path)

@st.cache_data(ttl=600)  # 缓存10分钟
def load_data():
    """从数据库加载文章数据"""
    conn = init_connection()
    query = """
    SELECT
        article_id,
        title,
        url,
        score,
        analysis,
        created_at
    FROM article_scores
    ORDER BY created_at DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    # 解析分析数据中的额外信息
    if 'analysis' in df.columns and not df.empty:
        df['summary'] = df['analysis'].apply(lambda x: eval(x).get('summary', '') if x else '')
        df['verdict'] = df['analysis'].apply(lambda x: eval(x).get('verdict', '') if x else '')
        df['reason'] = df['analysis'].apply(lambda x: eval(x).get('reason', '') if x else '')

    # 转换日期格式
    df['created_at'] = pd.to_datetime(df['created_at'])

    return df

def main():
    st.title("📰 RSS 文章分析仪表板")

    # 加载数据
    with st.spinner("正在加载数据..."):
        df = load_data()

    # 显示总体统计
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总文章数", len(df))
    with col2:
        avg_score = df['score'].mean() if not df.empty else 0
        st.metric("平均评分", f"{avg_score:.2f}")
    with col3:
        high_score_count = len(df[df['score'] >= 4.0]) if not df.empty else 0
        st.metric("高分文章(≥4.0)", high_score_count)
    with col4:
        low_score_count = len(df[df['score'] <= 2.0]) if not df.empty else 0
        st.metric("低分文章(≤2.0)", low_score_count)

    # 评分分布柱状图
    st.subheader("📊 评分分布")
    if not df.empty:
        fig_hist = px.histogram(
            df,
            x='score',
            nbins=20,
            title='文章评分分布',
            labels={'score': '评分', 'count': '文章数量'}
        )
        st.plotly_chart(fig_hist, use_container_width=True)

    # 时间趋势图
    st.subheader("📈 时间趋势")
    if not df.empty:
        df['date'] = df['created_at'].dt.date
        daily_stats = df.groupby('date').agg({
            'score': 'mean',
            'article_id': 'count'
        }).rename(columns={'article_id': 'count'}).reset_index()

        fig_trend = px.line(
            daily_stats,
            x='date',
            y=['score', 'count'],
            title='每日平均评分和文章数量趋势',
            labels={'value': '数值', 'variable': '指标'},
            render_mode='svg'
        )
        st.plotly_chart(fig_trend, use_container_width=True)

    # 文章搜索和筛选
    st.subheader("🔍 文章搜索和筛选")

    # 侧边栏筛选器
    st.sidebar.header("筛选选项")

    # 评分范围筛选
    score_range = st.sidebar.slider(
        "评分范围",
        float(df['score'].min()) if not df.empty else 0.0,
        float(df['score'].max()) if not df.empty else 5.0,
        (0.0, 5.0)
    )

    # 日期范围筛选
    if not df.empty:
        min_date = df['created_at'].min().date()
        max_date = df['created_at'].max().date()
        date_range = st.sidebar.date_input(
            "日期范围",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date
        )

        # 如果只选择了一个日期，将其转换为范围
        if isinstance(date_range, tuple) and len(date_range) == 1:
            date_range = (date_range[0], date_range[0])

    # 应用筛选
    filtered_df = df.copy()
    filtered_df = filtered_df[
        (filtered_df['score'] >= score_range[0]) &
        (filtered_df['score'] <= score_range[1])
    ]

    if 'date_range' in locals():
        filtered_df = filtered_df[
            (filtered_df['created_at'].dt.date >= date_range[0]) &
            (filtered_df['created_at'].dt.date <= date_range[1])
        ]

    # 搜索框
    search_term = st.sidebar.text_input("搜索文章标题或URL", "")
    if search_term:
        filtered_df = filtered_df[
            filtered_df['title'].str.contains(search_term, case=False, na=False) |
            filtered_df['url'].str.contains(search_term, case=False, na=False)
        ]

    # 排序选项
    sort_by = st.sidebar.selectbox(
        "排序方式",
        ["评分降序", "评分升序", "时间降序", "时间升序", "标题A-Z", "标题Z-A"]
    )

    if sort_by == "评分降序":
        filtered_df = filtered_df.sort_values('score', ascending=False)
    elif sort_by == "评分升序":
        filtered_df = filtered_df.sort_values('score', ascending=True)
    elif sort_by == "时间降序":
        filtered_df = filtered_df.sort_values('created_at', ascending=False)
    elif sort_by == "时间升序":
        filtered_df = filtered_df.sort_values('created_at', ascending=True)
    elif sort_by == "标题A-Z":
        filtered_df = filtered_df.sort_values('title', ascending=True)
    elif sort_by == "标题Z-A":
        filtered_df = filtered_df.sort_values('title', ascending=False)

    # 显示筛选后的结果
    st.write(f"找到 {len(filtered_df)} 篇符合条件的文章")

    # 分页显示
    items_per_page = 10
    total_pages = max(1, len(filtered_df) // items_per_page + (1 if len(filtered_df) % items_per_page > 0 else 0))
    page = st.number_input(
        "页码",
        min_value=1,
        max_value=total_pages,
        value=1,
        step=1
    )

    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_df = filtered_df.iloc[start_idx:end_idx]

    # 显示文章列表
    for _, row in page_df.iterrows():
        with st.expander(f"⭐ {row['score']:.1f}/5.0 - {row['title'][:80]}{'...' if len(row['title']) > 80 else ''}"):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"**标题:** {row['title']}")
                st.write(f"**评分:** ⭐ {row['score']}/5.0")
                st.write(f"**日期:** {row['created_at']}")

                if pd.notna(row.get('url')) and row['url']:
                    st.markdown(f"**链接:** [{row['url']}]({row['url']})")

                if pd.notna(row.get('summary')) and row['summary']:
                    st.write(f"**摘要:** {row['summary']}")

                if pd.notna(row.get('verdict')) and row['verdict']:
                    st.write(f"**结论:** {row['verdict']}")

                if pd.notna(row.get('reason')) and row['reason']:
                    st.write(f"**原因:** {row['reason']}")

            with col2:
                st.write("**操作:**")
                if st.button(f"🔗 打开", key=f"btn_{row['article_id']}"):
                    if pd.notna(row.get('url')) and row['url']:
                        st.markdown(f'<script>window.open("{row["url"]}", "_blank")</script>', unsafe_allow_html=True)

    # 下载数据
    st.sidebar.subheader("导出数据")
    if st.sidebar.button("下载筛选结果为 CSV"):
        csv = filtered_df.to_csv(index=False)
        st.sidebar.download_button(
            label="点击下载",
            data=csv,
            file_name=f"rss_articles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()