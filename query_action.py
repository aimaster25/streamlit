from elasticsearch import Elasticsearch
from pymongo import MongoClient
from datetime import datetime
import asyncio
from google.generativeai import configure, GenerativeModel
import os
from dotenv import load_dotenv


class DatabaseSearch:
    """데이터베이스 연결 및 검색 기능을 담당하는 클래스"""

    def __init__(self):
        # MongoDB 연결 설정
        try:
            self.mongo_client = MongoClient(
                "mongodb://localhost:27017/", serverSelectionTimeoutMS=5000
            )
            self.mongo_client.server_info()  # 연결 테스트
            self.db = self.mongo_client["crawlingdb"]
            self.mongo_collection = self.db["articles"]
        except Exception as e:
            print(f"MongoDB 연결 실패: {e}")
            raise

        # Elasticsearch 연결 설정
        try:
            self.es = Elasticsearch(["http://localhost:9200"])
            if not self.es.ping():
                raise ConnectionError("Elasticsearch 서버에 연결할 수 없습니다.")
        except Exception as e:
            print(f"Elasticsearch 연결 실패: {e}")
            raise

    def create_es_index(self):
        """Elasticsearch 인덱스 생성"""
        settings = {
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "mapping": {"total_fields": {"limit": 2000}},
                "index": {
                    "mapping": {"nested_fields": {"limit": 100}, "depth": {"limit": 20}}
                },
                "analysis": {
                    "analyzer": {
                        "korean": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": ["lowercase", "trim", "stop"],
                        }
                    }
                },
            },
            "mappings": {
                "dynamic": False,
                "properties": {
                    "title": {
                        "type": "text",
                        "analyzer": "korean",
                        "fields": {
                            "keyword": {"type": "keyword"},
                            "english": {"type": "text", "analyzer": "english"},
                            "ngram": {"type": "text", "analyzer": "standard"},
                        },
                    },
                    "cleaned_content": {
                        "type": "text",
                        "analyzer": "korean",
                        "fields": {
                            "english": {"type": "text", "analyzer": "english"},
                            "ngram": {"type": "text", "analyzer": "standard"},
                        },
                    },
                    "original_content": {
                        "type": "text",
                        "analyzer": "korean",
                        "fields": {
                            "english": {"type": "text", "analyzer": "english"},
                            "ngram": {"type": "text", "analyzer": "standard"},
                        },
                    },
                    "url": {"type": "keyword"},
                    "crawled_date": {
                        "type": "date",
                        "format": "strict_date_optional_time||epoch_millis",
                    },
                    "published_date": {
                        "type": "date",
                        "format": "strict_date_optional_time||epoch_millis",
                    },
                    "categories": {"type": "keyword"},
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "word_count": {"type": "integer"},
                            "sentence_count": {"type": "integer"},
                            "common_words": {"type": "object", "enabled": False},
                        },
                    },
                },
            },
        }

        try:
            if self.es.indices.exists(index="news_articles"):
                self.es.indices.delete(index="news_articles")
            self.es.indices.create(index="news_articles", body=settings)
            print("Elasticsearch 인덱스가 생성되었습니다.")
        except Exception as e:
            print(f"인덱스 생성 중 오류 발생: {e}")
            raise

    def sync_mongodb_to_elasticsearch(self):
        """MongoDB의 데이터를 Elasticsearch로 동기화"""
        self.create_es_index()
        mongo_docs = self.mongo_collection.find()
        success_count = 0
        error_count = 0

        for doc in mongo_docs:
            try:
                doc_id = str(doc.pop("_id"))
                cleaned_doc = {
                    "title": doc.get("title", ""),
                    "cleaned_content": doc.get("cleaned_content", ""),
                    "url": doc.get("url", ""),
                    "crawled_date": doc.get("crawled_date", ""),
                    "published_date": doc.get("published_date", ""),
                    "categories": doc.get("categories", []),
                    "metadata": {
                        "word_count": doc.get("metadata", {}).get("word_count", 0),
                        "sentence_count": doc.get("metadata", {}).get(
                            "sentence_count", 0
                        ),
                        "common_words": doc.get("metadata", {}).get("common_words", {}),
                    },
                }
                self.es.index(index="news_articles", id=doc_id, body=cleaned_doc)
                success_count += 1

                if success_count % 100 == 0:
                    print(f"{success_count}개의 문서가 성공적으로 동기화되었습니다.")

            except Exception as e:
                print(f"문서 동기화 중 오류 발생: {str(e)[:200]}...")
                error_count += 1
                continue

        print(f"\n동기화 완료:")
        print(f"성공: {success_count}개")
        print(f"실패: {error_count}개")

    @staticmethod
    def extract_keywords_from_query(query):
        """자연어 쿼리에서 핵심 키워드 추출"""
        stop_words = set(
            [
                "은",
                "는",
                "이",
                "가",
                "을",
                "를",
                "에",
                "에서",
                "로",
                "으로",
                "언제",
                "어디서",
                "어떻게",
                "무엇을",
                "누가",
                "왜",
                "있나요",
                "있어요",
                "인가요",
                "했나요",
                "됐나요",
                "열렸어",
                "있어",
            ]
        )
        words = query.replace("?", "").replace(".", "").split()
        keywords = [word for word in words if word not in stop_words]
        return keywords

    async def semantic_search(self, query, size=7):
        """의미 기반 검색 수행"""
        try:
            keywords = self.extract_keywords_from_query(query)
            keywords_str = " ".join(keywords)

            search_query = {
                "query": {
                    "bool": {
                        "should": [
                            {
                                "match_phrase": {
                                    "cleaned_content": {
                                        "query": query,
                                        "boost": 5,
                                        "slop": 2,
                                    }
                                }
                            },
                            {
                                "multi_match": {
                                    "query": keywords_str,
                                    "fields": [
                                        "title^3",
                                        "title.ngram^2",
                                        "cleaned_content^2",
                                        "cleaned_content.ngram",
                                    ],
                                    "type": "best_fields",
                                    "operator": "or",
                                    "fuzziness": "AUTO",
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "highlight": {
                    "fields": {
                        "title": {"number_of_fragments": 1},
                        "cleaned_content": {
                            "number_of_fragments": 3,
                            "fragment_size": 150,
                        },
                    },
                    "pre_tags": ["<strong>"],
                    "post_tags": ["</strong>"],
                },
                "_source": [
                    "title",
                    "cleaned_content",
                    "url",
                    "crawled_date",
                    "published_date",
                    "categories",
                ],
                "size": size,
                "sort": [{"_score": "desc"}],
            }

            result = self.es.search(index="news_articles", body=search_query)

            processed_results = []
            for hit in result["hits"]["hits"]:
                source = hit["_source"]
                highlights = hit.get("highlight", {})

                content_preview = " ... ".join(highlights.get("cleaned_content", []))
                if not content_preview:
                    content_preview = source["cleaned_content"][:300] + "..."

                processed_results.append(
                    {
                        "title": source["title"],
                        "content": source["cleaned_content"],
                        "content_preview": content_preview,
                        "url": source["url"],
                        "crawled_date": source.get("crawled_date", "날짜 정보 없음"),
                        "published_date": source.get(
                            "published_date", "날짜 정보 없음"
                        ),
                        "categories": source.get("categories", []),
                        "score": hit["_score"],
                        "highlights": highlights,
                    }
                )

            return processed_results

        except Exception as e:
            print(f"검색 중 오류 발생: {e}")
            return []


class ResponseGeneration:
    """초기 답변 생성을 담당하는 클래스"""

    def __init__(self):
        # API 키 설정
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
        configure(api_key=api_key)
        self.model = GenerativeModel("gemini-2.0-flash-exp")

    async def find_relevant_article(self, query, articles):
        """관련 기사 찾기"""
        keywords = set(query.lower().replace("?", " ").replace("!", " ").split())
        best_article = None
        max_score = 0

        for article in articles:
            text = (article["title"] + " " + article["content"]).lower()
            score = sum(1 for keyword in keywords if keyword in text)

            if score > max_score:
                max_score = score
                best_article = article

        if not best_article or max_score == 0:
            return None, 0.0

        relevance = max_score / len(keywords)
        return best_article, min(relevance, 1.0)

    async def generate_initial_response(self, query, articles):
        """초기 답변 생성"""
        # 의도 파악
        intent_prompt = f"""다음 질문의 의도를 파악하여 검색에 사용할 핵심 키워드와 컨텍스트를 추출하세요:

질문: {query}

다음 형식으로 답변하세요:
1. 질문 유형: (사실 확인/날짜 확인/방법 설명/의견 요청/비교 분석 중 선택)
2. 핵심 키워드: (검색에 사용할 중요 단어들)
3. 찾아야 할 정보: (기사에서 찾아야 할 구체적인 정보)"""

        intent_response = self.model.generate_content(intent_prompt)
        intent_analysis = intent_response.text

        if not articles:
            # 기사가 없는 경우
            knowledge_prompt = f"""당신은 AI 뉴스 전문 챗봇입니다.
            
질문 분석:
{intent_analysis}

관련된 뉴스 기사를 찾을 수 없어 일반적인 지식을 기반으로 답변합니다.

답변 시 다음 사항을 준수해주세요:
1. 뉴스 인용이나 시간 정보는 제외합니다.
2. 일반적인 사실과 개념 위주로 설명합니다.
3. 최신 정보가 필요한 경우 "관련 최신 정보 없음"을 명시합니다.
4. 정보의 한계를 명확히 설명합니다.

답변 형식:
1. 핵심 답변: (질문에 대한 직접적인 답변)
2. 개념 설명: (주요 개념과 배경 지식)
3. 한계 설명: (정보의 한계와 주의사항)"""

            response = self.model.generate_content(knowledge_prompt)
            return None, [], 0.0, response.text, intent_analysis

        best_article = articles[0]
        if best_article["score"] < 0.3:
            # 관련성이 낮은 경우
            hybrid_prompt = self._create_hybrid_prompt(
                query, intent_analysis, best_article
            )
            response = self.model.generate_content(hybrid_prompt)
            return (
                best_article,
                articles[1:9],
                best_article["score"],
                response.text,
                intent_analysis,
            )

        # 기사 내용이 충분한 경우
        full_context_prompt = self._create_full_context_prompt(
            query,
            intent_analysis,
            best_article,
            articles[1:] if len(articles) > 1 else [],
        )
        response = self.model.generate_content(full_context_prompt)
        return (
            best_article,
            articles[1:9],
            best_article["score"],
            response.text,
            intent_analysis,
        )

    def _create_hybrid_prompt(self, query, intent_analysis, best_article):
        """하이브리드 프롬프트 생성"""
        return f"""당신은 AI 뉴스 전문 챗봇입니다.

질문 분석:
{intent_analysis}

관련성이 다소 낮은 뉴스 기사가 있습니다:
제목: {best_article['title']}
내용: {best_article['content']}
발행일: {best_article.get('published_date', '날짜 정보 없음')}

지침:
1. 기사의 관련 내용을 부분적으로 활용하세요.
2. AI 모델의 기본 지식을 활용하여 부족한 정보를 보완하세요.
3. 기사 정보와 일반 지식을 구분하여 제시하세요.
4. 정보의 출처(뉴스/일반 지식)를 명확히 표시하세요.

형식:
1. 직접 답변: (기사 내용 + 일반 지식 결합)
2. 뉴스 정보: (관련 기사 내용 인용)
3. 보충 설명: (AI 모델의 기본 지식 활용)
4. 정보 출처: (각 정보의 출처 명시)"""

    def _create_full_context_prompt(
        self, query, intent_analysis, best_article, related_articles
    ):
        """전체 컨텍스트 프롬프트 생성"""
        return f"""당신은 AI 뉴스 전문 챗봇입니다.

질문 분석:
{intent_analysis}

주요 참고 기사:
제목: {best_article['title']}
내용: {best_article['content']}
발행일: {best_article.get('published_date', '날짜 정보 없음')}

추가 참고 기사들:
{' '.join([f"- {art['title']} ({art.get('published_date', '날짜 정보 없음')})" for art in related_articles[:3]])}

지침:
1. 질문 유형에 맞는 적절한 형식으로 답변하세요.
2. 기사의 내용을 우선적으로 활용하세요.
3. 필요한 경우 AI 모델의 배경 지식을 활용하여 맥락을 보완하세요.
4. 기사 정보와 배경 지식을 구분하여 제시하세요.

답변 형식:
1. 핵심 답변: (질문 의도에 맞는 직접적인 답변)
2. 뉴스 근거: (관련 기사 내용 인용)
3. 맥락 설명: (기사 내용 + 보완적 배경 지식)
4. 시간 정보: (관련 사건의 시간 순서나 날짜 정보)"""


class ResponseReview:
    """답변 검토 및 개선을 담당하는 클래스"""

    def __init__(self, model):
        self.model = model

    async def review_and_enhance_response(
        self, query, initial_response, intent_analysis, best_article, has_articles=True
    ):
        """답변 검토 및 개선"""
        if has_articles:
            review_prompt = self._create_article_review_prompt(
                query, initial_response, intent_analysis, best_article
            )
        else:
            review_prompt = self._create_general_review_prompt(
                query, initial_response, intent_analysis
            )

        review_response = self.model.generate_content(review_prompt)
        review_text = review_response.text

        return initial_response if "원본 답변 사용" in review_text else review_text

    def _create_article_review_prompt(
        self, query, initial_response, intent_analysis, best_article
    ):
        """기사 기반 검토 프롬프트 생성"""
        return f"""사용자의 질문과 AI의 답변을 검토하여 개선이 필요한지 평가해주세요.

원래 질문: {query}
질문 의도 분석: {intent_analysis}
주요 기사 정보:
- 제목: {best_article['title']}
- 내용 요약: {best_article['content'][:300]}...
- 발행일: {best_article.get('published_date', '날짜 정보 없음')}
AI의 답변: {initial_response}

검토 기준:
1. 질문 의도 부합도
2. 뉴스 기사 활용도
3. 답변의 완성도
4. 시간 정보의 정확성
5. 형식의 적절성
6. 다중 기사 통합 분석
7. 맥락 설명의 충분성

답변이 개선이 필요한 경우, 위 형식을 유지하면서 답변을 개선하고 개선된 답변만 말해주세요.
개선이 필요없는 경우 "원본 답변 사용"이라고만 답변해주세요."""

    def _create_general_review_prompt(self, query, initial_response, intent_analysis):
        """일반 검토 프롬프트 생성"""
        return f"""사용자의 질문과 AI의 답변을 검토하여 개선이 필요한지 평가해주세요.

원래 질문: {query}
질문 의도 분석: {intent_analysis}
AI의 답변: {initial_response}

검토 기준:
1. 질문 의도 부합도
2. 답변의 완성도와 정확성
3. 설명의 명확성과 논리성
4. 불필요하거나 누락된 정보
5. 답변 형식의 적절성

답변이 개선이 필요한 경우, 위 형식을 유지하면서 답변을 개선하고 개선된 답변만 말해주세요.
개선이 필요없는 경우 "원본 답변 사용"이라고만 답변해주세요."""


class NewsChatbot:
    """통합 뉴스 챗봇 클래스"""

    def __init__(self):
        self.db_search = DatabaseSearch()
        self.response_gen = ResponseGeneration()
        self.response_review = ResponseReview(self.response_gen.model)

    async def process_query(self, query):
        """사용자 쿼리 처리"""
        try:
            # 1. 관련 기사 검색
            articles = await self.db_search.semantic_search(query)

            # 2. 초기 답변 생성
            (
                best_article,
                related_articles,
                relevance_score,
                initial_response,
                intent_analysis,
            ) = await self.response_gen.generate_initial_response(query, articles)

            # 3. 답변 검토 및 개선
            final_response = await self.response_review.review_and_enhance_response(
                query,
                initial_response,
                intent_analysis,
                best_article if articles else None,
                has_articles=bool(articles),
            )

            return best_article, related_articles, relevance_score, final_response

        except Exception as e:
            print(f"쿼리 처리 중 오류 발생: {e}")
            return None, [], 0.0, "처리 중 오류가 발생했습니다."

    async def run(self):
        """챗봇 실행"""
        print("챗봇을 초기화하는 중...")

        try:
            print("\n향상된 AI 뉴스 챗봇이 준비되었습니다!")
            print("'exit' 또는 'quit'을 입력하면 종료됩니다.")
            print("질문을 입력해주세요.\n")

            while True:
                user_input = input("사용자: ").strip()
                if not user_input:
                    continue

                if user_input.lower() in ["exit", "quit"]:
                    print("챗봇을 종료합니다!")
                    break

                print("\n처리 중...", end="\r")

                try:
                    main_article, related_articles, score, response = (
                        await self.process_query(user_input)
                    )

                    print("\n챗봇: ", response)

                    if main_article and score > 0.2:
                        self._display_article_info(
                            main_article, score, related_articles
                        )

                except Exception as e:
                    print(f"\n오류가 발생했습니다: {str(e)}")
                    print("다시 시도해주세요.\n")

        except Exception as e:
            print(f"챗봇 실행 중 오류 발생: {str(e)}")

    def _display_article_info(self, main_article, score, related_articles):
        """기사 정보 출력"""
        print(f"\n주요 참고 기사:")
        print(f"제목: {main_article['title']}")
        print(f"관련도: {score:.2f}")
        print(f"URL: {main_article['url']}")
        if "categories" in main_article:
            print(f"카테고리: {', '.join(main_article['categories'])}")
        print(f"작성일: {main_article.get('crawled_date', '날짜 정보 없음')}")

        if related_articles:
            print(f"\n관련 기사들:")
            for idx, article in enumerate(related_articles[:5], 1):
                print(f"\n{idx}. {article['title']}")
                print(f"   URL: {article['url']}")
                print(f"   발행일: {article.get('published_date', '날짜 정보 없음')}")
        print("")


async def main():
    """메인 실행 함수"""
    try:
        chatbot = NewsChatbot()
        await chatbot.run()
    except Exception as e:
        print(f"실행 중 오류 발생: {e}")
    finally:
        print("프로그램을 종료합니다.")


if __name__ == "__main__":
    try:
        # 데이터베이스 검색 객체 생성
        print("Elasticsearch 동기화를 시작합니다...")
        db_search = DatabaseSearch()

        # MongoDB에서 Elasticsearch로 데이터 동기화
        print("MongoDB의 데이터를 Elasticsearch로 동기화합니다...")
        db_search.sync_mongodb_to_elasticsearch()

        print("\n동기화가 완료되었습니다.")

    except Exception as e:
        print(f"오류 발생: {e}")
