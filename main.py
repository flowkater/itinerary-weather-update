from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc
import time
import csv
import os
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials


def get_weather_info_for_date(driver, url, date):
    # 페이지 로드
    driver.get(url)
    time.sleep(2)

    # "daily-wrapper" 클래스의 모든 div 요소 가져오기
    daily_wrappers = driver.find_elements(By.CLASS_NAME, "daily-wrapper")

    for wrapper in daily_wrappers:
        # 날짜 확인
        date_element = wrapper.find_element(By.CSS_SELECTOR, "h2.date .sub.date")
        if date_element.text == date:
            # 요일, 날짜
            day_of_week = wrapper.find_element(
                By.CSS_SELECTOR, "h2.date .dow.date"
            ).text
            date_text = date_element.text

            # 날씨 아이콘
            weather_icon = wrapper.find_element(
                By.CSS_SELECTOR, "svg.icon"
            ).get_attribute("data-src")

            # 온도 (최저, 최고)
            high_temp = wrapper.find_element(By.CSS_SELECTOR, "div.temp .high").text
            low_temp = wrapper.find_element(By.CSS_SELECTOR, "div.temp .low").text
            # 최저기온에서 '/' 문자 제거
            low_temp = low_temp.replace("/", "")

            # half-day-card-content의 날씨 코멘트
            weather_comment = wrapper.find_element(
                By.CSS_SELECTOR, "div.half-day-card-content .phrase"
            ).text

            # 링크 정보 가져오기
            link = wrapper.find_element(
                By.CSS_SELECTOR, "a.daily-forecast-card"
            ).get_attribute("href")

            return {
                "day_of_week": day_of_week,
                "date": date_text,
                "weather_icon": weather_icon,
                "high_temp": high_temp,
                "low_temp": low_temp,
                "weather_comment": weather_comment,
                "detail_link": link,
            }

    return None


def get_detailed_weather_info(driver, link):
    # 상세 페이지로 이동
    driver.get(link)
    # 페이지 로딩 대기
    time.sleep(2)

    # 상세 정보 파싱
    try:
        # half-day-card 요소들 가져오기 (낮/밤 정보)
        half_day_cards = driver.find_elements(
            By.CSS_SELECTOR, ".half-day-card.content-module"
        )
        detailed_data = {"day": {}, "night": {}}

        for idx, card in enumerate(half_day_cards[:2]):  # 낮/밤 두 개의 카드만 처리
            # 낮인지 밤인지 확인
            try:
                title = card.find_element(
                    By.CSS_SELECTOR, ".half-day-card-header__title h2.title"
                ).text
                time_category = "day" if title == "낮" else "night"

                # 아이콘 정보
                weather_icon = card.find_element(
                    By.CSS_SELECTOR, "svg.icon"
                ).get_attribute("data-src")

                # 온도 정보
                temperature = card.find_element(
                    By.CSS_SELECTOR, ".temperature"
                ).text.strip()
                temp_label = card.find_element(
                    By.CSS_SELECTOR, ".hi-lo-label"
                ).text.strip()

                # RealFeel 정보
                realfeel_temp = (
                    card.find_element(By.CSS_SELECTOR, ".real-feel > div:first-child")
                    .text.split("RealFeel®")[1]
                    .strip()
                    .split("°")[0]
                    .strip()
                    + "°"
                )
                realfeel_comment = ""
                try:
                    realfeel_comment = card.find_element(
                        By.CSS_SELECTOR, ".real-feel .label"
                    ).text.strip()
                except:
                    pass

                # 날씨 설명
                weather_phrase = card.find_element(
                    By.CSS_SELECTOR, ".half-day-card-content .phrase"
                ).text.strip()

                # 패널 정보 (강수 확률, 강수량 등)
                panels_data = {}

                # 왼쪽 패널
                left_panel_items = card.find_elements(
                    By.CSS_SELECTOR, ".panels .left .panel-item"
                )
                for item in left_panel_items:
                    try:
                        key = item.text.split("\n")[0].strip()
                        value = item.find_element(
                            By.CSS_SELECTOR, ".value"
                        ).text.strip()
                        panels_data[key] = value
                    except:
                        pass

                # 오른쪽 패널
                right_panel_items = card.find_elements(
                    By.CSS_SELECTOR, ".panels .right .panel-item"
                )
                for item in right_panel_items:
                    try:
                        key = item.text.split("\n")[0].strip()
                        value = item.find_element(
                            By.CSS_SELECTOR, ".value"
                        ).text.strip()
                        panels_data[key] = value
                    except:
                        pass

                # 데이터 저장
                detailed_data[time_category] = {
                    "title": title,
                    "weather_icon": weather_icon,
                    "temperature": temperature,
                    "temp_label": temp_label,
                    "realfeel_temp": realfeel_temp,
                    "realfeel_comment": realfeel_comment,
                    "weather_phrase": weather_phrase,
                    "details": panels_data,
                }

            except Exception as e:
                print(f"카드 파싱 중 오류 발생: {e}")
                continue

        return detailed_data

    except Exception as e:
        print(f"상세 날씨 정보 파싱 오류: {e}")
        return None


def filter_future_dates(dates):
    """
    오늘 날짜 이후의 날짜만 필터링합니다.

    Args:
        dates: 날짜 문자열 리스트 (예: ["4. 15.", "4. 16."])

    Returns:
        오늘 이후의 날짜 리스트
    """
    today = datetime.now()
    filtered_dates = []

    for date_str in dates:
        # 날짜 문자열 파싱 (예: "4. 15." -> 4월 15일)
        try:
            month, day = map(int, date_str.replace(".", "").split())
            date_obj = datetime(today.year, month, day)

            # 오늘 날짜 이후인 경우만 포함
            if date_obj >= today:
                filtered_dates.append(date_str)
        except ValueError:
            print(f"날짜 파싱 오류: {date_str}")
            continue

    return filtered_dates


def get_weather_data_for_locations(cities_dates_map):
    """
    여러 도시와 날짜에 대한 날씨 정보를 가져옵니다.

    Args:
        cities_dates_map: 도시별 URL과 날짜 목록을 포함하는 딕셔너리

    Returns:
        각 도시별, 날짜별 날씨 정보를 포함하는 딕셔너리
    """
    # 헤드리스 모드 설정

    # GitHub Actions 환경인지 확인
    is_github_actions = os.getenv("GITHUB_ACTIONS") == "true"

    options = Options()
    # 로그 레벨 최소화
    options.add_argument("--log-level=3")
    # options.add_argument("--headless=new")  # 새로운 헤드리스 모드
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")

    # 절대 user-data-dir 사용하지 않음
    options.add_argument("--incognito")  # 시크릿 모드 사용

    if is_github_actions:
        from webdriver_manager.chrome import ChromeDriverManager

        # # GitHub Actions 환경에서는 undetected_chromedriver 사용
        print("GitHub Actions 환경에서 실행 중...")
        try:
            # undetected-chromedriver를 사용하여 강화된 안정성
            print("undetected-chromedriver를 사용하여 드라이버 초기화 시도...")
            options.add_argument("--disable-blink-features=AutomationControlled")
            # headless 모드는 undetected-chromedriver에서 다르게 설정
            uc_options = uc.ChromeOptions()
            uc_options.add_argument("--headless")
            uc_options.add_argument("--no-sandbox")
            uc_options.add_argument("--disable-dev-shm-usage")
            uc_options.add_argument("--disable-gpu")
            uc_options.add_argument("--disable-extensions")
            uc_options.add_argument("--incognito")
            driver = uc.Chrome(options=uc_options)
            print("undetected-chromedriver로 초기화 성공")
        except Exception as e:
            print(f"undetected-chromedriver 초기화 실패: {e}")
            try:
                # 실패한 경우 일반 Chrome 시도
                print("일반 Chrome 드라이버로 시도...")
                driver = webdriver.Chrome(options=options)
                print("일반 Chrome 드라이버 초기화 성공")
            except Exception as e2:
                print(f"일반 Chrome 드라이버도 실패: {e2}")
                # 디버깅 정보 출력
                import subprocess

                print("Chrome 설정 정보:")
                subprocess.run(["google-chrome", "--version"], check=False)
                subprocess.run(["which", "google-chrome"], check=False)
                subprocess.run(["chromedriver", "--version"], check=False)
                subprocess.run(["which", "chromedriver"], check=False)
                raise
    else:
        # 로컬 환경에서는 로컬 ChromeDriver 사용
        print("로컬 환경에서 실행 중...")
        chromedriver_path = "chromedriver/chromedriver"
        service = Service(executable_path=chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)

    weather_data = {}

    try:
        for city_name, city_info in cities_dates_map.items():
            city_url = city_info["url"]
            dates = city_info["dates"]

            # 오늘 이후의 날짜만 필터링
            future_dates = filter_future_dates(dates)
            if not future_dates:
                print(f"{city_name}: 오늘 이후의 날짜가 없습니다.")
                continue

            print(
                f"{city_name}의 다음 날짜들에 대한 날씨 정보를 가져옵니다: {', '.join(future_dates)}"
            )

            city_weather_data = {}

            for date in future_dates:
                print(f"{city_name} - {date} 날씨 정보 가져오는 중...")

                # 기본 날씨 정보 가져오기
                weather_info = get_weather_info_for_date(driver, city_url, date)

                if weather_info:
                    # 상세 날씨 정보 가져오기
                    detailed_info = get_detailed_weather_info(
                        driver, weather_info["detail_link"]
                    )

                    if detailed_info:
                        # 기본 정보와 상세 정보 합치기
                        complete_weather_info = {
                            "basic_info": weather_info,
                            "detailed_info": detailed_info,
                        }

                        city_weather_data[date] = complete_weather_info
                        print(f"{city_name} - {date} 날씨 정보 가져오기 완료")
                    else:
                        print(
                            f"{city_name} - {date} 상세 날씨 정보를 가져오지 못했습니다."
                        )
                else:
                    print(f"{city_name} - {date} 기본 날씨 정보를 찾을 수 없습니다.")

            if city_weather_data:
                weather_data[city_name] = city_weather_data

    finally:
        # 브라우저 종료
        driver.quit()

    return weather_data


def save_weather_data_to_csv(weather_data, output_file="weather_data_test.csv"):
    """
    날씨 데이터를 CSV 파일로 저장합니다.

    Args:
        weather_data: 날씨 정보를 담은 딕셔너리
        output_file: 저장할 CSV 파일명
    """
    # CSV 파일 헤더 정의
    headers = [
        "날짜",
        "도시명",
        "요일",
        "날씨 설명",
        "최고기온",
        "최저기온",
        "체감온도 (RealFeel)",
        "낮 강수량 (mm)",
        "낮 강수 확률",
        "낮 날씨 설명",
        "밤 강수량 (mm)",
        "밤 강수 확률",
        "밤 날씨 설명",
        "낮 아이콘",
        "밤 아이콘",
    ]

    # 모든 데이터를 리스트로 변환
    all_rows = []
    for city_name, city_data in weather_data.items():
        for date, weather_info in city_data.items():
            basic_info = weather_info["basic_info"]
            detailed_info = weather_info["detailed_info"]

            # 낮 정보 추출
            day_info = detailed_info.get("day", {})
            day_precipitation = day_info.get("details", {}).get("비", "N/A")
            # 강수량에서 'mm' 제거하고 숫자만 추출
            if day_precipitation != "N/A":
                day_precipitation = day_precipitation.replace("mm", "").strip()
                # 작은따옴표 제거
                day_precipitation = day_precipitation.replace("'", "")
                # 0.0 값 처리
                if day_precipitation == "0.0" or day_precipitation == "0":
                    day_precipitation = "0.0"
            day_precipitation_prob = day_info.get("details", {}).get("강수 확률", "N/A")
            day_weather_phrase = day_info.get("weather_phrase", "N/A")
            day_icon = day_info.get("weather_icon", "N/A")

            # 밤 정보 추출
            night_info = detailed_info.get("night", {})
            night_precipitation = night_info.get("details", {}).get("비", "N/A")
            # 강수량에서 'mm' 제거하고 숫자만 추출
            if night_precipitation != "N/A":
                night_precipitation = night_precipitation.replace("mm", "").strip()
                # 작은따옴표 제거
                night_precipitation = night_precipitation.replace("'", "")
                # 0.0 값 처리
                if night_precipitation == "0.0" or night_precipitation == "0":
                    night_precipitation = "0.0"
            night_precipitation_prob = night_info.get("details", {}).get(
                "강수 확률", "N/A"
            )
            night_weather_phrase = night_info.get("weather_phrase", "N/A")
            night_icon = night_info.get("weather_icon", "N/A")

            # RealFeel 온도 추출 (낮 정보에서 가져옴)
            realfeel_temp = day_info.get("realfeel_temp", "N/A")

            # CSV 행 작성
            row = [
                date,
                city_name,
                basic_info["day_of_week"],
                basic_info["weather_comment"],
                basic_info["high_temp"],
                basic_info["low_temp"],
                realfeel_temp,
                day_precipitation,
                day_precipitation_prob,
                day_weather_phrase,
                night_precipitation,
                night_precipitation_prob,
                night_weather_phrase,
                day_icon,
                night_icon,
            ]
            all_rows.append(row)

    # 날짜와 도시 순서로 정렬
    all_rows.sort(key=lambda x: (x[0], list(weather_data.keys()).index(x[1])))

    # CSV 파일 생성
    with open(output_file, mode="w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(all_rows)

    print(f"날씨 데이터가 {output_file}에 저장되었습니다.")


def update_google_sheet(csv_file, spreadsheet_name, worksheet_name):
    """
    CSV 파일의 데이터를 구글 시트에 업데이트합니다.

    Args:
        csv_file: CSV 파일 경로
        spreadsheet_name: 구글 스프레드시트 이름
        worksheet_name: 워크시트 이름
    """
    # 구글 API 인증 설정
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]

    # credentials.json 파일이 필요합니다. 구글 클라우드 콘솔에서 다운로드 받아야 합니다.
    credentials = ServiceAccountCredentials.from_json_keyfile_name(
        "credentials.json", scope
    )
    gc = gspread.authorize(credentials)

    # 스프레드시트 열기
    try:
        spreadsheet = gc.open(spreadsheet_name)
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"스프레드시트 '{spreadsheet_name}'를 찾을 수 없습니다.")
        return

    # 워크시트 열기
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
    except gspread.exceptions.WorksheetNotFound:
        print(f"워크시트 '{worksheet_name}'를 찾을 수 없습니다.")
        return

    # CSV 파일 읽기
    with open(csv_file, "r", encoding="utf-8-sig") as file:
        csv_data = list(csv.reader(file))

    # 시트 업데이트
    worksheet.clear()  # 기존 데이터 지우기
    worksheet.update("A1", csv_data)  # 새로운 데이터 업데이트

    print(
        f"구글 시트 '{spreadsheet_name}'의 '{worksheet_name}' 워크시트가 업데이트되었습니다."
    )


def format_time_delta(seconds):
    """
    초 단위 시간을 시:분:초 형식으로 변환합니다.
    """
    return str(timedelta(seconds=int(seconds)))


# 도시 정보와 날짜 정의
cities_dates = {
    # "베네치아": {
    #     "url": "https://www.accuweather.com/ko/it/venice/216711/daily-weather-forecast/216711",
    #     "dates": ["4. 11.", "4. 15.", "4. 16.", "4. 17.", "4. 18."],
    # },
    # "피렌체": {
    #     "url": "https://www.accuweather.com/ko/it/florence/216189/daily-weather-forecast/216189",
    #     "dates": ["4. 18.", "4. 19.", "4. 20.", "4. 21.", "4. 22.", "4. 23."],
    # },
    "시에나": {
        "url": "https://www.accuweather.com/ko/it/siena/216196/daily-weather-forecast/216196",
        "dates": ["4. 20."],
    },
    # "피사": {
    #     "url": "https://www.accuweather.com/ko/it/pisa/216194/daily-weather-forecast/216194",
    #     "dates": ["4. 21.", "4. 22."],
    # },
    # "나폴리": {
    #     "url": "https://www.accuweather.com/ko/it/naples/212466/daily-weather-forecast/212466",
    #     "dates": ["4. 23.", "4. 24.", "4. 25."],
    # },
    # "아말피": {
    #     "url": "https://www.accuweather.com/ko/it/amalfi/212365/daily-weather-forecast/212365",
    #     "dates": ["4. 25.", "4. 26.", "4. 27.", "4. 28.", "4. 29."],
    # },
    # "포지타노": {
    #     "url": "https://www.accuweather.com/ko/it/positano/212430/weather-forecast/212430",
    #     "dates": ["4. 26.", "4. 27.", "4. 28."],
    # },
    # "카프리": {
    #     "url": "https://www.accuweather.com/ko/it/capri/212416/daily-weather-forecast/212416",
    #     "dates": ["4. 26.", "4. 27.", "4. 28."],
    # },
    # "로마": {
    #     "url": "https://www.accuweather.com/ko/it/rome/213490/daily-weather-forecast/213490",
    #     "dates": ["4. 29.", "4. 30.", "5. 1.", "5. 2.", "5. 3."],
    # },
}

if __name__ == "__main__":
    # 시작 시간 기록
    start_time = time.time()
    print(f"스크래핑 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # # 모든 도시와 날짜에 대한 날씨 정보 가져오기
    all_weather_data = get_weather_data_for_locations(cities_dates)

    # # CSV 파일로 저장
    save_weather_data_to_csv(all_weather_data)

    # 구글 시트 업데이트
    update_google_sheet("weather_data_test.csv", "이탈리아 날씨", "날씨 데이터")

    # 종료 시간 기록 및 실행 시간 계산
    end_time = time.time()
    total_time = end_time - start_time
    print(f"스크래핑 종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"총 실행 시간: {format_time_delta(total_time)}")
