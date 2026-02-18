# EPUB AI Translator

## About
EPUB 파일의 일본어 라이트노벨을 LLM을 사용해 한국어로 번역한 EPUB 파일을 출력하는 프로그램입니다.

## Reqiurements
* **이 소프트웨어의 라이선스를 정독하고 이해/동의할 것.**
* python 3.14
* CUDA support GPU (로컬 모델을 사용하는 경우)

## Installation
### 수동 설치
**Linux(RHEL, Fedora)**
```bash
# install reqiurements
sudo dnf install git make python3.14 pass gpg pinentry-curses-y

# install
git clone github.com/shwan6160/EPUB-AI-Translator.git
cd EPUB-AI-Translator
make install

# setup pass as credential storage
gpg --full-generate-key
pass init "user@example.com"
```

**Windows**
```cmd
winget install Git.Git GnuWin32.Make Python.Python.3.14

git clone github.com/shwan6160/EPUB-AI-Translator.git
cd EPUB-AI-Translator
make install
```

## Project Structure
* main.py - entrypoint
* prompts
    * dictionary.py - char dict gen prompt
    * translation - translate prompt
* utils.py - util functions
* epub.py - epub class & epub unzip functions
* exceptions.py - custom Exceptions
* settings.py - settings object

## License
이 프로젝트는 unlicense 라이선스를 채택하고 있습니다.

이 프로젝트의 소스코드는 퍼블릭 도메인이며, 이 코드에 대해 저작자는 어떠한 보증도 하지 않습니다.
이 프로젝트 또는 이 프로젝트의 소스코드를 이용해 발생하는 어떤 종류의 문제에서던지 저작자에 대해서는 면책으로 합니다.

자세한 내용은 LICENSE 파일을 참고하십시오.

**이 소프트웨어 또는 소스코드를 사용하기 전에 반드시 LICENSE를 정독하고 이해하십시오.**


## TODO
- [x] 프롬프트 설계
- [ ] 여러 API 사용한 번역 지원
    - [x] 모델 사용을 위한 기본 인터페이스 클래스 구현
    - [x] 서드파티 API 프로바이더 대응 클래스 구현
    - [ ] 서드파티 API 번역 코드 추가
- [ ] Rosetta 27B와 Gemma 3 27B를 이용한 완전 로컬 작동 구현
    - [ ] Rosetta 27B 프롬프트 설계
    - [ ] 로컬 모델 추론 코드 작성
    - [ ] 로컬 모델 인터페이스 클래스 구현
- [ ] 필요했던 추가 기능들
    - [x] html tag 살려서 디자인 및 레이아웃, 하이퍼링크 살리기
    - [ ] cli 프로그램화 하기
        - [ ] 옵션 받도록 하기
        - [x] 프로그래스바 작성
    - [ ] 웹 대시보드 추가하기
        - [ ] 웹 컨트롤 기능 및 파일 추가 기능
        - [ ] 웹 실시간 json 편집