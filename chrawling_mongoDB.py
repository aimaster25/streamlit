import requests
from bs4 import BeautifulSoup
import time
from pymongo import MongoClient
import re
from datetime import datetime


def get_full_article_content(article_url):
    """기사 본문 내용을 가져오는 함수"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3",
    }

    try:
        response = requests.get(article_url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        article_content = soup.find(attrs={"itemprop": "articleBody"})

        if article_content:
            all_text = article_content.stripped_strings
            content = " ".join(
                text for text in all_text if text and not text.startswith("//")
            )
            return content if content else "본문 내용을 찾을 수 없습니다."

        return "본문을 찾을 수 없습니다."

    except requests.exceptions.RequestException as e:
        return f"기사 내용 가져오기 실패: {e}"


def get_article_date(soup):
    """기사의 실제 발행일을 추출하는 함수"""
    try:
        # 1. 기사 목록에서 날짜 찾기
        date_text = None
        lis = soup.select("li")
        for li in lis:
            text = li.get_text().strip()
            if re.search(r"\d{2}\.\d{2}\.\d{2}\s+\d{2}:\d{2}", text):
                date_text = re.search(
                    r"\d{2}\.\d{2}\.\d{2}\s+\d{2}:\d{2}", text
                ).group()
                break

        # 2. 다른 위치에서도 날짜 찾기 (백업)
        if not date_text:
            all_spans = soup.find_all("span")
            for span in all_spans:
                text = span.get_text().strip()
                if re.search(r"\d{2}\.\d{2}\.\d{2}\s+\d{2}:\d{2}", text):
                    date_text = re.search(
                        r"\d{2}\.\d{2}\.\d{2}\s+\d{2}:\d{2}", text
                    ).group()
                    break

        if date_text:
            current_year_prefix = str(datetime.now().year)[:2]
            parsed_date = datetime.strptime(
                f"{current_year_prefix}{date_text}", "%Y.%m.%d %H:%M"
            )
            return parsed_date.isoformat()

        return None

    except Exception:
        return None


def get_latest_article_info():
    """MongoDB에서 가장 최근에 크롤링된 기사의 정보를 가져오는 함수"""
    try:
        # 가장 최근 크롤링된 기사 찾기
        latest_article = mongo_collection.find_one({}, sort=[("crawled_date", -1)])
        return latest_article
    except Exception as e:
        print(f"최근 기사 정보 조회 중 오류 발생: {e}")
        return None


def check_article_exists(url):
    """특정 URL의 기사가 이미 DB에 존재하는지 확인하는 함수"""
    try:
        return mongo_collection.find_one({"url": url}) is not None
    except Exception as e:
        print(f"기사 존재 여부 확인 중 오류 발생: {e}")
        return False


def crawl_page(page_number):
    """페이지별 기사를 크롤링하는 함수"""
    url = f"https://www.newstheai.com/news/articleList.html?view_type=sm&page={page_number}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.select(".view-cont")

        if articles:
            print(f"\n=== 페이지 {page_number} ===")
            new_articles_found = False

            for idx, article in enumerate(articles, start=1):
                title = article.select_one(".titles")
                link_elem = article.select_one("a[href*='articleView.html']")

                if title and link_elem:
                    title_text = title.get_text(strip=True)
                    article_url = "https://www.newstheai.com" + link_elem["href"]

                    # 이미 크롤링된 기사인지 확인
                    if check_article_exists(article_url):
                        print(f"기사 {idx}: 이미 크롤링됨 - {title_text}")
                        continue

                    print(f"\n기사 {idx} 내용 가져오는 중...")

                    # 기사 내용과 날짜를 가져오기 위한 요청
                    article_response = requests.get(article_url, headers=headers)
                    article_response.raise_for_status()
                    article_soup = BeautifulSoup(article_response.text, "html.parser")

                    # 본문 내용 가져오기
                    article_content = article_soup.find(
                        attrs={"itemprop": "articleBody"}
                    )
                    if article_content:
                        all_text = article_content.stripped_strings
                        full_content = " ".join(
                            text
                            for text in all_text
                            if text and not text.startswith("//")
                        )
                    else:
                        full_content = "본문 내용을 찾을 수 없습니다."

                    # 발행일 가져오기
                    published_date = get_article_date(article_soup)

                    # MongoDB에 저장
                    save_to_mongodb(
                        page_number,
                        idx,
                        title_text,
                        article_url,
                        full_content,
                        published_date,
                    )
                    new_articles_found = True
                    time.sleep(1)

            print(
                f"\n페이지 {page_number}에서 {'새로운 기사를 찾았습니다.' if new_articles_found else '새로운 기사를 찾지 못했습니다.'}"
            )
            return new_articles_found

        print(f"\n페이지 {page_number}에서 기사를 찾을 수 없습니다.")
        return False

    except requests.exceptions.RequestException as e:
        print(f"페이지 {page_number} 크롤링 중 오류 발생: {e}")
        return False


def clean_text(text):
    """텍스트 정제 함수"""
    if not text:
        return ""

    # HTML 태그 제거
    text = re.sub(r"<[^>]+>", "", text)

    # 특수문자 제거 (단, 한글, 영문, 숫자, 일부 문장부호는 유지)
    text = re.sub(r"[^\w\s.!?~%]", " ", text)

    # 중복 공백 제거
    text = re.sub(r"\s+", " ", text)

    # 앞뒤 공백 제거
    return text.strip()


def analyze_content(content):
    """콘텐츠 분석하여 메타데이터 추출"""
    # 단어 수 계산
    words = content.split()
    word_count = len(words)

    # 문장 수 계산
    sentences = re.split(r"[.!?]+", content)
    sentence_count = len([s for s in sentences if s.strip()])

    # 자주 등장하는 단어 추출 (2글자 이상)
    word_freq = {}
    for word in words:
        if len(word) >= 2:
            word_freq[word] = word_freq.get(word, 0) + 1

    # 상위 10개 단어 추출
    common_words = dict(
        sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:10]
    )

    return {
        "word_count": word_count,
        "sentence_count": sentence_count,
        "common_words": common_words,
    }


def categorize_content(content):
    """콘텐츠 카테고리 분류"""
    categories = []
    content_lower = content.lower()

    # 카테고리 키워드 정의
    keywords = {
        "AI": ["인공지능", "머신러닝", "딥러닝", "ai", "학습", "알고리즘"],
        "Business": ["비즈니스", "스타트업", "투자", "기업", "시장"],
        "Tech": ["기술", "개발", "프로그래밍", "소프트웨어", "플랫폼"],
        "Research": ["연구", "개발", "논문", "특허", "기술"],
    }

    for category, words in keywords.items():
        if any(word.lower() in content_lower for word in words):
            categories.append(category)

    return categories


def save_to_mongodb(
    page_number, article_number, title, url, content, published_date=None
):
    """크롤링한 내용을 전처리하여 MongoDB에 저장하는 함수"""
    # 텍스트 정제
    cleaned_content = clean_text(content)

    # 콘텐츠 분석
    content_analysis = analyze_content(cleaned_content)

    # 카테고리 분류
    categories = categorize_content(cleaned_content)

    article_data = {
        "page_number": page_number,
        "article_number": article_number,
        "title": clean_text(title),
        "url": url,
        "original_content": content,
        "cleaned_content": cleaned_content,
        "metadata": content_analysis,
        "categories": categories,
        "published_date": published_date,  # 실제 발행일
        "crawled_date": datetime.now().isoformat(),
    }

    try:
        existing_article = mongo_collection.find_one({"url": url})

        if existing_article:
            mongo_collection.update_one({"url": url}, {"$set": article_data})
            print(f"MongoDB에서 업데이트 완료: {title}")
        else:
            mongo_collection.insert_one(article_data)
            print(f"MongoDB에 새로 저장 완료: {title}")
            print(f"카테고리: {categories}")
            print(f"발행일: {published_date or '날짜 정보 없음'}")
            print(f"단어 수: {content_analysis['word_count']}")

    except Exception as e:
        print(f"MongoDB 저장 중 오류 발생: {e}")


if __name__ == "__main__":
    # MongoDB 연결 설정
    try:
        mongo_client = MongoClient(
            "mongodb://localhost:27017/", serverSelectionTimeoutMS=5000
        )
        mongo_client.server_info()  # 연결 테스트
        db = mongo_client["crawlingdb"]
        mongo_collection = db["articles"]

        # MongoDB 인덱스 생성
        mongo_collection.create_index([("url", 1)], unique=True)
        mongo_collection.create_index([("categories", 1)])  # 카테고리 검색 최적화
        mongo_collection.create_index([("crawled_date", 1)])  # 날짜 검색 최적화
    except Exception as e:
        print(f"MongoDB 연결 실패: {e}")
        exit(1)

    try:
        # 최근 크롤링된 기사 정보 확인
        latest_article = get_latest_article_info()
        if latest_article:
            print(f"\n최근 크롤링된 기사 정보:")
            print(f"제목: {latest_article.get('title', 'N/A')}")
            print(f"크롤링 일자: {latest_article.get('crawled_date', 'N/A')}")

        # 크롤링 시작
        page_number = 1
        max_pages = 75
        consecutive_no_new = 0  # 연속으로 새로운 기사가 없는 페이지 수
        max_consecutive_no_new = (
            3  # 이 값 이상 연속으로 새로운 기사가 없으면 크롤링 중단
        )

        while page_number <= max_pages:
            print(f"\n페이지 {page_number} 처리 중...")
            found_new_articles = crawl_page(page_number)

            if not found_new_articles:
                consecutive_no_new += 1
                print(f"페이지 {page_number}에서 새로운 기사를 찾지 못했습니다.")

                if consecutive_no_new >= max_consecutive_no_new:
                    print(
                        f"\n{max_consecutive_no_new}페이지 연속으로 새로운 기사가 없어 크롤링을 종료합니다."
                    )
                    break
            else:
                consecutive_no_new = 0  # 새로운 기사를 찾으면 카운터 리셋

            page_number += 1

        print("\n크롤링 및 데이터 전처리가 완료되었습니다.")
        print("결과가 MongoDB에 저장되었습니다.")

    except Exception as e:
        print(f"오류 발생: {e}")

    finally:
        mongo_client.close()
        print("MongoDB 연결이 종료되었습니다.")
