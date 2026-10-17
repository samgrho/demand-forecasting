"""Streamlit dashboard MVP."""

from datetime import date, timedelta
import os
import requests
import streamlit as st

st.set_page_config(page_title="Demand Forecasting", page_icon="📈", layout="wide")
st.title("📈 Local Demand Forecasting")

default_api = os.getenv("API_BASE_URL", "http://localhost:8000")
api_base_url = st.sidebar.text_input("API Base URL", value=default_api)

col1, col2, col3 = st.columns(3)
location = col1.text_input("Location", value="Boston, MA")
start_date = col2.date_input("Start Date", value=date.today())
end_date = col3.date_input("End Date", value=date.today() + timedelta(days=7))

if st.button("Run Forecast"):
    with st.spinner("Calculating forecast..."):
        payload = {
            "location": location,
            "start_date": str(start_date),
            "end_date": str(end_date),
        }
        try:
            response = requests.post(f"{api_base_url}/forecast", json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()

            st.metric("Demand Score", f"{data['demand_score']:.2f}")
            st.metric("Confidence", f"{data['confidence']:.0%}")

            st.subheader("Evidence")
            if not data.get("evidence"):
                st.info("No evidence items yet. Connect collectors to populate source-backed reporting.")
            else:
                for item in data["evidence"]:
                    st.markdown(f"- [{item['source_name']}]({item['source_url']}) — {item['summary']}")
        except Exception as exc:
            st.error(f"Request failed: {exc}")
