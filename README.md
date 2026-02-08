# EPUB AI Translator

## About - 개요
EPUB 파일의 일본어 라이트노벨을 LLM을 사용해 한국어로 번역한 EPUB 파일을 출력하는 프로그램입니다.

## Reqiurements - 요구사항
* python 3.14
* CUDA support GPU or TPU (로컬 모델을 사용하는 경우)

## TODO - 구현할 것
- [ ] 프롬프트 설계
- [ ] Gemini API 이용한 번역
- [ ] Rosetta 27B와 Gemma 3 27B를 이용한 완전 로컬 작동 구현
    - [ ] Rosetta 27B 프롬프트 설계
    - [ ] 로컬 모델 추론 코드 작성