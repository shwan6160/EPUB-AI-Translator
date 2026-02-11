# EPUB AI Translator

## About
EPUB 파일의 일본어 라이트노벨을 LLM을 사용해 한국어로 번역한 EPUB 파일을 출력하는 프로그램입니다.

## Reqiurements
* python 3.14
* CUDA support GPU (로컬 모델을 사용하는 경우)

## Project Structure
* main.py - entrypoint
* prompts
    * dictionary.py - char dict gen prompt
    * translation - translate prompt
* utils.py - util functions
* epub.py - epub class & epub unzip functions
* exceptions.py - custom Exceptions
* settings.py - settings object

## TODO
- [ ] 프롬프트 설계
- [ ] 여러 API 사용한 번역 지원
    - [x] 모델 사용을 위한 기본 인터페이스 클래스 구현
    - [ ] 서드파티 API 프로바이더 대응 클래스 구현
- [ ] Rosetta 27B와 Gemma 3 27B를 이용한 완전 로컬 작동 구현
    - [ ] Rosetta 27B 프롬프트 설계
    - [ ] 로컬 모델 추론 코드 작성
    - [ ] 로컬 모델 인터페이스 클래스 구현