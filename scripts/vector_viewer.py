import streamlit as st
import pandas as pd
import os
import sys
from dotenv import load_dotenv

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# Load env
load_dotenv(os.path.join(project_root, ".env"))

# Import vector store
try:
    from rss_analyzer.vector_store import vector_store
except ImportError:
    st.error("Failed to import vector_store. Make sure you are running from the project root.")
    st.stop()

st.set_page_config(page_title="ChromaDB Viewer", layout="wide")

st.title("📊 RSS ChromaDB Viewer")

# Sidebar for stats and actions
st.sidebar.header("Statistics")

try:
    count = vector_store.get_article_count()
    st.sidebar.metric("Total Articles", count)

    if st.sidebar.button("Refresh Data"):
        st.rerun()

    st.sidebar.divider()

    # Search functionality
    st.sidebar.subheader("Semantic Search")
    query = st.sidebar.text_input("Query", "AI")
    limit = st.sidebar.slider("Limit", 1, 20, 5)

    if st.sidebar.button("Search"):
        with st.spinner("Searching..."):
            results = vector_store.search_similar(query, limit=limit)
            st.session_state.search_results = results

except Exception as e:
    st.sidebar.error(f"Error connecting to ChromaDB: {e}")
    st.stop()

# Main content
tab1, tab2 = st.tabs(["Browse Articles", "Search Results"])

with tab1:
    st.subheader("All Articles")

    # Get all data
    try:
        all_data = vector_store.get_all_articles()

        if all_data['ids']:
            # Create DataFrame
            data_list = []
            for i in range(len(all_data['ids'])):
                aid = all_data['ids'][i]
                doc = all_data['documents'][i] if i < len(all_data['documents']) else ""
                meta = all_data['metadatas'][i] if i < len(all_data['metadatas']) else {}

                data_list.append({
                    "ID": aid,
                    "Title": meta.get("title", "N/A"),
                    "URL": meta.get("url", "N/A"),
                    "Score": meta.get("score", "N/A"),
                    "Updated": meta.get("updated_at", "N/A"),
                    "Content Preview": doc[:100] + "..." if len(doc) > 100 else doc
                })

            df = pd.DataFrame(data_list)
            st.dataframe(df, use_container_width=True)

            # Detail view
            selected_id = st.selectbox("Select Article ID to view details", df["ID"].tolist())
            if selected_id:
                sel_row = df[df["ID"] == selected_id].iloc[0]
                st.write(f"### {sel_row['Title']}")
                st.write(f"**URL:** {sel_row['URL']}")
                st.write(f"**Score:** {sel_row['Score']}")
                st.text_area("Full Content",
                             all_data['documents'][all_data['ids'].index(selected_id)],
                             height=200)
        else:
            st.info("Vector store is empty.")

    except Exception as e:
        st.error(f"Error fetching data: {e}")

with tab2:
    st.subheader(f"Search Results for: '{query}'")

    if "search_results" in st.session_state and st.session_state.search_results:
        results = st.session_state.search_results
        for res in results:
            with st.expander(f"{res['metadata'].get('title', 'Untitled')} (Score: {res['distance']:.4f})"):
                st.write(f"**URL:** {res['metadata'].get('url', 'N/A')}")
                st.write(f"**AI Score:** {res['metadata'].get('score', 'N/A')}")
                st.write(f"**Distance:** {res['distance']}")
                st.text(res['text'])
    elif "search_results" in st.session_state:
        st.info("No results found.")
    else:
        st.info("Enter a query in the sidebar and click Search.")
