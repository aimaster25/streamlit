import streamlit as st
import asyncio
from datetime import datetime
import pandas as pd
from query_action import DatabaseSearch, ResponseGeneration, ResponseReview, NewsChatbot

# 페이지 설정
st.set_page_config(
    page_title="AI 뉴스 챗봇",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 커스텀 CSS
st.markdown(
    """
    <style>
    .main {
        padding: 0rem 1rem;
    }
    .stAlert {
        padding: 1rem;
        margin: 1rem 0;
    }
    .chat-message {
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 1rem 0;
    }
    .article-card {
        border: 1px solid #ddd;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    </style>
""",
    unsafe_allow_html=True,
)


class StreamlitChatbot:
    def __init__(self):
        # 세션 상태 초기화
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []
        if "chatbot" not in st.session_state:
            st.session_state.chatbot = NewsChatbot()
        if "article_history" not in st.session_state:
            st.session_state.article_history = []
        if "search_history" not in st.session_state:
            st.session_state.search_history = set()

    def setup_sidebar(self):
        """사이드바 설정"""
        with st.sidebar:
            st.header("📊 챗봇 상태")
            st.write("연결된 데이터베이스:")
            st.info("MongoDB: 뉴스 기사 저장소\nElasticsearch: 검색 엔진")

            st.header("🔍 검색 히스토리")
            if st.session_state.search_history:
                for query in list(st.session_state.search_history)[-5:]:
                    st.text(f"• {query}")

            st.header("⚙️ 설정")
            if st.button("대화 내용 초기화"):
                st.session_state.chat_history = []
                st.session_state.article_history = []
                st.rerun()

    def display_article_info(self, article, score=None):
        """기사 정보 표시"""
        with st.container():
            st.markdown(
                f"""
                <div class="article-card">
                    <h4>📰 {article['title']}</h4>
                    <p><b>발행일:</b> {article.get('published_date', '날짜 정보 없음')}</p>
                    {f'<p><b>관련도:</b> {score:.2f}%</p>' if score else ''}
                    <p><b>🔗 기사 링크:</b> <a href="{article['url']}" target="_blank">{article['url']}</a></p>
                    <p><b>카테고리:</b> {', '.join(article.get('categories', ['미분류']))}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

    def display_chat_message(self, role, content, articles=None):
        """채팅 메시지 표시"""
        with st.chat_message(role):
            st.markdown(content)

            if articles and role == "assistant" and isinstance(articles, list):
                st.markdown("### 📚 관련 기사")

                # 기본 정보 표시
                for i in range(0, min(len(articles), 4), 2):
                    col1, col2 = st.columns(2)

                    # 첫 번째 열
                    with col1:
                        if i < len(articles) and isinstance(articles[i], dict):
                            article = articles[i]
                            st.markdown(
                                f"""
                        #### {i+1}. {article.get('title', '제목 없음')}
                        - 📅 발행일: {article.get('published_date', '날짜 정보 없음')}
                        - 🔗 [기사 링크]({article.get('url', '#')})
                        - 📊 카테고리: {', '.join(article.get('categories', ['미분류']))}
                        """
                            )

                    # 두 번째 열
                    with col2:
                        if i + 1 < len(articles) and isinstance(articles[i + 1], dict):
                            article = articles[i + 1]
                            st.markdown(
                                f"""
                        #### {i+2}. {article.get('title', '제목 없음')}
                        - 📅 발행일: {article.get('published_date', '날짜 정보 없음')}
                        - 🔗 [기사 링크]({article.get('url', '#')})
                        - 📊 카테고리: {', '.join(article.get('categories', ['미분류']))}
                        """
                            )

    async def process_user_input(self, user_input):
        """사용자 입력 처리"""
        if not user_input:
            return

        # 사용자 메시지 표시
        self.display_chat_message("user", user_input)
        st.session_state.chat_history.append(("user", user_input))
        st.session_state.search_history.add(user_input)

        # 처리 중 표시
        with st.status("AI가 답변을 생성하고 있습니다...") as status:
            try:
                # 챗봇 응답 생성
                status.update(label="관련 기사를 검색중입니다...")
                main_article, related_articles, score, response = (
                    await st.session_state.chatbot.process_query(user_input)
                )

                status.update(label="답변을 생성하고 있습니다...")
                # 응답 저장 및 표시
                st.session_state.chat_history.append(
                    (
                        "assistant",
                        response,
                        [main_article] + related_articles if main_article else [],
                    )
                )
                self.display_chat_message(
                    "assistant",
                    response,
                    [main_article] + related_articles if main_article else None,
                )

                # 기사 히스토리 업데이트
                if main_article:
                    st.session_state.article_history.append(main_article)

                status.update(label="완료!", state="complete")

            except Exception as e:
                st.error(f"오류가 발생했습니다: {str(e)}")
                status.update(label="오류 발생", state="error")

    def show_analytics(self):
        """분석 정보 표시"""
        if st.session_state.article_history:  # 기사 히스토리가 있는 경우만 표시
            st.header("📊 검색 분석")

            # 1. 카테고리 분포 분석
            categories = []
            for article in st.session_state.article_history:
                categories.extend(article.get("categories", ["미분류"]))

            df_categories = pd.DataFrame(categories, columns=["카테고리"])
            category_counts = df_categories["카테고리"].value_counts()

            # 2. 시간별 기사 분포 분석
            dates = [
                datetime.fromisoformat(
                    art.get("published_date", datetime.now().isoformat())
                )
                for art in st.session_state.article_history
            ]
            df_dates = pd.DataFrame(dates, columns=["발행일"])
            date_counts = df_dates["발행일"].dt.date.value_counts()

            # 분석 결과 표시
            col1, col2 = st.columns(2)

            with col1:
                st.subheader("📈 카테고리별 기사 분포")
                if not category_counts.empty:
                    st.bar_chart(category_counts)
                    # 카테고리별 비율 표시
                    st.markdown("**카테고리별 비율:**")
                    for cat, count in category_counts.items():
                        percentage = (count / len(categories)) * 100
                        st.write(f"- {cat}: {percentage:.1f}% ({count}건)")
                else:
                    st.info("아직 카테고리 데이터가 없습니다.")

            with col2:
                st.subheader("📅 일자별 기사 분포")
                if not date_counts.empty:
                    st.line_chart(date_counts)
                    # 최신순으로 날짜별 기사 수 표시
                    st.markdown("**날짜별 기사 수:**")
                    for date, count in date_counts.sort_index(ascending=False).items():
                        st.write(f"- {date.strftime('%Y-%m-%d')}: {count}건")
                else:
                    st.info("아직 날짜 데이터가 없습니다.")

            # 3. 검색 통계
            st.subheader("🔍 검색 통계")
            col3, col4, col5 = st.columns(3)

            with col3:
                st.metric(
                    label="총 검색 수", value=len(st.session_state.search_history)
                )

            with col4:
                st.metric(
                    label="검색된 총 기사 수",
                    value=len(st.session_state.article_history),
                )

            with col5:
                if st.session_state.article_history:
                    latest_article = max(
                        st.session_state.article_history,
                        key=lambda x: x.get("published_date", ""),
                    )
                    st.metric(
                        label="최신 기사 날짜",
                        value=datetime.fromisoformat(
                            latest_article.get(
                                "published_date", datetime.now().isoformat()
                            )
                        ).strftime("%Y-%m-%d"),
                    )

            # 4. 최근 검색어 히스토리
            if st.session_state.search_history:
                st.subheader("🕒 최근 검색어")
                recent_searches = list(st.session_state.search_history)[-5:]  # 최근 5개
                for query in reversed(recent_searches):
                    st.text(f"• {query}")
        else:
            st.info("아직 검색 결과가 없습니다. 질문을 입력해주세요!")


def main():
    app = StreamlitChatbot()
    app.setup_sidebar()

    st.title("📰 AI 뉴스 챗봇")

    # 챗봇 설명
    st.markdown(
        """
    ### 👋 안녕하세요! AI 뉴스 챗봇입니다.
    뉴스 기사에 대해 궁금한 점을 자유롭게 물어보세요. 관련 기사를 찾아 답변해드립니다.
    
    **예시 질문:**
    - "최근 AI 기술 동향이 궁금해요"
    - "스타트업 투자 현황에 대해 알려주세요"
    - "새로운 AI 서비스에는 어떤 것들이 있나요?"
    """
    )

    # 채팅 히스토리 표시
    for message in st.session_state.chat_history:
        if len(message) == 3:  # 챗봇 응답 (관련 기사 포함)
            app.display_chat_message(message[0], message[1], message[2])
        else:  # 사용자 메시지
            app.display_chat_message(message[0], message[1])

    # # 분석 정보 표시
    # app.show_analytics()

    # 사용자 입력
    user_input = st.chat_input("질문을 입력하세요...")
    if user_input:
        asyncio.run(app.process_user_input(user_input))


if __name__ == "__main__":
    main()
