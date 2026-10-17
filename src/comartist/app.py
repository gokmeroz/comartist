"""Minimal Streamlit entry point."""

import streamlit as st


def main() -> None:
    """Render the chapter brief input page."""
    st.set_page_config(page_title="ComArtist")
    st.title("ComArtist")
    st.text_area("Chapter brief", placeholder="What happens in this chapter?")


if __name__ == "__main__":
    main()
