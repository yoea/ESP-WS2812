/*
 * WeMOS D1 mini 电脑状态指示灯 - 固件端（哑终端）
 *
 * 职责：只负责把串口收到的 24 字节变成光，不含任何业务逻辑。
 * 所有策略（配色、优先级、平滑）都在电脑端 Python 里做，改灯效不用重新烧录。
 *
 * 帧格式： A5 5A | CMD | LEN | PAYLOAD[LEN] | CRC8
 *   CRC8 覆盖 CMD + LEN + PAYLOAD，多项式 0x07，初值 0x00
 *
 * 命令：
 *   0x01 SET_ALL      payload 24B，RGB 顺序，一次设定 8 颗灯珠
 *   0x03 BRIGHTNESS   payload 1B，全局亮度 0-255
 *   0x04 HEARTBEAT    payload 0B
 *   0x06 OFF          payload 0B，立即熄灭
 *   0x07 STATUS_LED   payload 1B，板载 LED 常驻灯态：0=灭 1=常亮 2=慢闪
 *   0x08 STATUS_PULSE payload 1B，板载 LED 短闪几下后自动熄灭（事件提示）
 *   0x10 HANDSHAKE    payload 0B，回应固件版本号，用于电脑端确认固件匹配
 *
 * 板载 LED（GPIO2 / D4，低电平点亮）—— 只在「有事发生」时出声。
 * 「在放歌 / 在跑 CPU 条」这两件事 8 颗灯珠已经说得很清楚了，这颗灯再复述一遍
 * 纯属打扰，所以主机端平时根本不点它，只在事件瞬间发一条脉冲：
 *   切歌      闪 2 下（0x08 payload=2）
 *   状态切换  闪 3 下（0x08 payload=3）
 * 脉冲结束自动回到熄灭，其余时间全灭。
 *
 * 主机失联时转成「温柔呼吸」，用 PWM 渐亮渐暗：
 *   超过 HEARTBEAT_TIMEOUT 没收到任何帧，且主机最后一条不是 OFF -> 呼吸
 *   主机主动退出会先发 OFF，这时保持熄灭 —— 手动关掉不误报。
 *   上电后主机一直没连上，同样会进入呼吸，表示「固件在跑但没人在推数据」。
 *   进入呼吸前会等灯带渐灭走完：PWM 一开就不能再 show()，顺序不能反。
 *
 * 为什么这里敢用 analogWrite：ESP8266 的 PWM 靠定时器中断实现，会打断 WS2812 的
 * 软件位翻转 —— 但呼吸只在「主机已经不发数据」的窗口里启用，这段时间一次
 * strip.show() 都不会调用，没有位翻转，也就没有可被打断的时序。
 * 收到任何一帧立刻退出 PWM、恢复成纯 digitalWrite。
 * （GPIO2 同时是 strapping 引脚，低电平点亮 + 外部上拉：上电是高=灭，不干扰启动。）
 *
 * 保护机制：
 *   - 帧解析带超时重置，一串干扰字节不会把状态机卡死
 *   - 心跳超时(3s)后自动渐暗到灭：电脑关机/休眠/进程退出时不会僵在最后一帧
 */

#include <Adafruit_NeoPixel.h>
#include <ESP8266WiFi.h>

#define LED_PIN    4          // D2（已从 GPIO0 迁出：GPIO0 是 strapping 引脚，上电被拉低会进下载模式）
#define LED_COUNT  8
#define BAUD_RATE  115200

#define HDR0              0xA5
#define HDR1              0x5A
#define MAX_PAYLOAD       32
#define FRAME_TIMEOUT_MS  100
#define HEARTBEAT_TIMEOUT 3000
#define FADE_STEP_MS      60
#define FADE_STEP         5

#define CMD_SET_ALL    0x01
#define CMD_BRIGHTNESS 0x03
#define CMD_HEARTBEAT  0x04
#define CMD_OFF        0x06
#define CMD_STATUS_LED 0x07
#define CMD_STATUS_PULSE 0x08
#define CMD_HANDSHAKE  0x10

#define FIRMWARE_VERSION 3

// ---- 板载 LED ----
#define STATUS_LED_PIN   2      // D4 / GPIO2，与灯带数据脚(D2/GPIO4)无关
#define STATUS_OFF       0
#define STATUS_ON        1
#define STATUS_BLINK     2
#define BLINK_NORMAL_MS  1000   // 常驻慢闪：1s 亮/灭，周期 2s = 0.5Hz（0x07 = 2 时才用）
#define PULSE_ON_MS      90     // 事件脉冲：亮 90ms
#define PULSE_GAP_MS     130    // 事件脉冲：灭 130ms（2 下约 0.44s，3 下约 0.66s）
#define PULSE_MAX        10     // 一次最多闪几下，防止主机传个 200 把它闪成频闪灯
#define BREATHE_PERIOD_MS 2600  // 失联呼吸周期：2.6s 一个来回，慢到不心慌
#define BREATHE_FLOOR    0.05f  // 呼吸最暗（占空比）
#define BREATHE_CEIL     0.55f  // 呼吸最亮 —— 刻意不到满档，报警也要温柔

Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

// ---- 帧解析状态机 ----
enum ParseState { WAIT_HDR0, WAIT_HDR1, WAIT_CMD, WAIT_LEN, WAIT_PAYLOAD, WAIT_CRC };
ParseState pstate = WAIT_HDR0;

uint8_t buf[2 + MAX_PAYLOAD];   // buf[0]=CMD  buf[1]=LEN  buf[2..]=PAYLOAD
uint8_t payloadIdx = 0;
uint32_t lastByteMs = 0;
uint32_t lastFrameMs = 0;

// ---- 亮度与渐灭 ----
uint8_t targetBrightness = 128;
uint8_t currentLevel = 128;
bool    fading = false;
uint32_t lastFadeMs = 0;

// ---- 板载 LED ----
uint8_t statusMode  = STATUS_OFF;   // 主机用 0x07 设定的常驻灯态
bool    hostSaidOff = false;        // 主机主动熄过灯（正常退出），这种停心跳不报警
bool    statusLit   = false;        // 当前实际电平，避免每轮重复 digitalWrite

bool     breatheOn = false;         // PWM 呼吸模式占用中
uint8_t  pulseLeft = 0;             // 还需要闪几下
bool     pulseLit  = false;         // 当前这一拍是亮着的
uint32_t pulseMark = 0;             // 当前这一拍的起始时刻

void statusLedWrite(bool on) {
  if (breatheOn) return;            // PWM 正占着这个脚，别用 digitalWrite 去抢
  if (on == statusLit) return;
  statusLit = on;
  digitalWrite(STATUS_LED_PIN, on ? LOW : HIGH);   // 低电平点亮
}

// 主机没打招呼就走了：最后一条命令不是 OFF，却已经 HEARTBEAT_TIMEOUT 没有数据
bool statusAlarm() {
  return !hostSaidOff && (millis() - lastFrameMs) > HEARTBEAT_TIMEOUT;
}

// 进入 PWM 呼吸。前提是灯带已经不需要再 show()（渐灭走完了，或压根没连上主机）
void enterBreathe() {
  if (breatheOn) return;
  strip.clear();                    // 此刻没有数据流，这次 show 是安全的
  strip.show();
  analogWriteRange(255);
  analogWriteFreq(1000);            // 1kHz 远高于人眼临界，看不出一格一格
  breatheOn = true;
}

// 退出 PWM，把引脚交还给 digitalWrite。收到任何一帧都要先调它 —— 否则那帧的
// show() 会跑在 PWM 中断里被打断，这正是本文件唯一要提防的时序冲突。
void leaveBreathe() {
  if (!breatheOn) return;
  breatheOn = false;
  analogWrite(STATUS_LED_PIN, 255);     // 占空比拉满 = 引脚恒高 = 灭
  digitalWrite(STATUS_LED_PIN, HIGH);   // digitalWrite 内部会解除 PWM 对该脚的占用
  statusLit = false;
}

void breatheStep() {
  float phase = (millis() % BREATHE_PERIOD_MS) / (float)BREATHE_PERIOD_MS;
  float wave  = 0.5f - 0.5f * cosf(2.0f * PI * phase);          // 0 -> 1 -> 0，从最暗起步
  float level = BREATHE_FLOOR + (BREATHE_CEIL - BREATHE_FLOOR) * wave;
  // 低电平点亮，占空比要反过来：越亮 -> 低电平占比越高
  analogWrite(STATUS_LED_PIN, (int)((1.0f - level) * 255.0f + 0.5f));
}

void pulseStart(uint8_t n) {
  if (breatheOn) return;            // 失联优先，这时候不闪事件脉冲
  if (n < 1) n = 1;
  if (n > PULSE_MAX) n = PULSE_MAX;
  pulseLeft = n;
  pulseLit  = true;
  pulseMark = millis();
  statusLedWrite(true);
}

void pulseStop() {
  pulseLeft = 0;
  pulseLit  = false;
  statusLedWrite(false);
}

void pulseStep() {
  uint32_t now = millis();
  if (pulseLit) {                   // 亮拍：到点转灭拍，这一次就算闪完了
    if (now - pulseMark >= PULSE_ON_MS) {
      statusLedWrite(false);
      pulseLit  = false;
      pulseMark = now;
      pulseLeft--;
    }
  } else if (pulseLeft > 0) {       // 灭拍：歇够了再来一下
    if (now - pulseMark >= PULSE_GAP_MS) {
      statusLedWrite(true);
      pulseLit  = true;
      pulseMark = now;
    }
  }
}

// 每轮 loop 调一次。优先级：主机失联(呼吸) > 事件脉冲 > 主机指定的常驻灯态
void updateStatusLed() {
  if (statusAlarm()) {
    // 灯带还在渐灭就先不接管：渐灭里有 show()，PWM 一开就会打断 WS2812 时序。
    // 等它灭完再呼吸，视觉上也正好是「灯光缓缓熄灭 → 板载灯接手」的接力。
    if (fading && currentLevel > 0) {
      statusLedWrite(false);
      return;
    }
    enterBreathe();
    breatheStep();
    return;
  }

  leaveBreathe();

  if (pulseLit || pulseLeft > 0) {
    pulseStep();
    return;
  }

  // 常驻灯态：主机端平时只发 0（全灭），1/2 留着备用
  if (statusMode == STATUS_BLINK) {
    statusLedWrite((millis() % (BLINK_NORMAL_MS * 2)) < BLINK_NORMAL_MS);
  } else if (statusMode == STATUS_ON) {
    statusLedWrite(true);
  } else {
    statusLedWrite(false);
  }
}

static uint8_t crc8(const uint8_t *data, size_t n) {
  uint8_t c = 0x00;
  for (size_t i = 0; i < n; i++) {
    c ^= data[i];
    for (uint8_t b = 0; b < 8; b++) {
      c = (c & 0x80) ? (uint8_t)((c << 1) ^ 0x07) : (uint8_t)(c << 1);
    }
  }
  return c;
}

void resetParser() {
  pstate = WAIT_HDR0;
  payloadIdx = 0;
}

void sendFrame(uint8_t cmd, const uint8_t *payload, uint8_t len) {
  uint8_t out[2 + MAX_PAYLOAD];
  out[0] = cmd;
  out[1] = len;
  if (len) memcpy(out + 2, payload, len);
  uint8_t crc = crc8(out, 2 + len);
  Serial.write(HDR0);
  Serial.write(HDR1);
  Serial.write(out, 2 + len);
  Serial.write(crc);
}

void handleFrame(uint8_t cmd, const uint8_t *payload, uint8_t len) {
  // 只要还有数据过来就退出 PWM 呼吸：接下来这一帧要 show()，引脚必须先回到
  // 纯开关模式，否则 WS2812 的位翻转会被 PWM 中断打断。
  leaveBreathe();

  switch (cmd) {
    case CMD_SET_ALL: {
      if (len < LED_COUNT * 3) return;
      for (uint8_t i = 0; i < LED_COUNT; i++) {
        strip.setPixelColor(i, strip.Color(payload[i * 3],
                                           payload[i * 3 + 1],
                                           payload[i * 3 + 2]));
      }
      // 收到有效数据就从渐灭状态唤醒
      if (fading) {
        fading = false;
        currentLevel = targetBrightness;
        strip.setBrightness(currentLevel);
      }
      hostSaidOff = false;         // 主机在正常推流，撤销「主动熄灯」标记
      strip.show();
      break;
    }

    case CMD_BRIGHTNESS: {
      if (len < 1) return;
      targetBrightness = payload[0];
      currentLevel = targetBrightness;
      fading = false;
      strip.setBrightness(currentLevel);
      strip.show();
      break;
    }

    case CMD_HEARTBEAT:
      break;

    case CMD_OFF: {
      strip.clear();
      strip.show();
      currentLevel = 0;
      fading = false;
      // 「关灯」是整套关掉：板载 LED 一起灭，且之后停心跳也不进呼吸报警
      pulseStop();
      statusMode  = STATUS_OFF;
      hostSaidOff = true;
      break;
    }

    case CMD_STATUS_LED: {
      if (len < 1) return;
      statusMode = payload[0];
      break;
    }

    case CMD_STATUS_PULSE: {
      if (len < 1) return;
      pulseStart(payload[0]);
      break;
    }

    case CMD_HANDSHAKE: {
      uint8_t ver = FIRMWARE_VERSION;
      sendFrame(CMD_HANDSHAKE, &ver, 1);
      break;
    }
  }
}

void setup() {
  WiFi.mode(WIFI_OFF);          // 关 WiFi：省电，且消除干扰 WS2812 时序的中断源

  // 板载 LED 先钉死为灭（GPIO2 上电本就是高，这里只是别让它悬空）
  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, HIGH);

  Serial.setRxBufferSize(512);
  Serial.begin(BAUD_RATE);

  strip.begin();
  strip.setBrightness(targetBrightness);
  strip.show();

  // 开机自检：灯带蓝色闪一下 + 板载 LED 连眨 3 下，表示固件已跑起来。
  // 之后若主机一直不连，3 秒后会转成温柔呼吸 —— 那是在说「没人在推数据」，不是坏了。
  strip.fill(strip.Color(0, 0, 90));
  strip.show();
  for (uint8_t i = 0; i < 3; i++) {
    digitalWrite(STATUS_LED_PIN, LOW);
    delay(70);
    digitalWrite(STATUS_LED_PIN, HIGH);
    delay(80);
  }
  statusLit = false;            // 上面绕过了 statusLedWrite，手动同步缓存
  strip.clear();
  strip.show();

  lastFrameMs = millis();
}

void loop() {
  // 1) 非阻塞读串口
  while (Serial.available()) {
    uint8_t b = (uint8_t)Serial.read();
    lastByteMs = millis();

    switch (pstate) {
      case WAIT_HDR0:
        if (b == HDR0) pstate = WAIT_HDR1;
        break;

      case WAIT_HDR1:
        if (b == HDR1) pstate = WAIT_CMD;
        else if (b != HDR0) resetParser();
        break;

      case WAIT_CMD:
        buf[0] = b;
        pstate = WAIT_LEN;
        break;

      case WAIT_LEN:
        if (b > MAX_PAYLOAD) { resetParser(); break; }
        buf[1] = b;
        payloadIdx = 0;
        pstate = (b == 0) ? WAIT_CRC : WAIT_PAYLOAD;
        break;

      case WAIT_PAYLOAD:
        buf[2 + payloadIdx++] = b;
        if (payloadIdx >= buf[1]) pstate = WAIT_CRC;
        break;

      case WAIT_CRC: {
        if (crc8(buf, 2 + buf[1]) == b) {
          lastFrameMs = millis();
          handleFrame(buf[0], buf + 2, buf[1]);
        }
        resetParser();
        break;
      }
    }
  }

  // 2) 半帧超时重置：防止一串干扰字节把状态机卡死
  if (pstate != WAIT_HDR0 && (millis() - lastByteMs) > FRAME_TIMEOUT_MS) {
    resetParser();
  }

  // 3) 心跳超时：电脑关机 / 休眠 / 进程退出时自动渐暗到灭
  if (!fading && (millis() - lastFrameMs) > HEARTBEAT_TIMEOUT) {
    fading = true;
    lastFadeMs = millis();
  }
  if (fading && currentLevel > 0 && (millis() - lastFadeMs) > FADE_STEP_MS) {
    lastFadeMs = millis();
    currentLevel = (currentLevel > FADE_STEP) ? (currentLevel - FADE_STEP) : 0;
    strip.setBrightness(currentLevel);
    strip.show();
  }

  // 4) 板载 LED：正常态由主机指定，主机失联转 4Hz 报警
  updateStatusLed();

  yield();   // 喂看门狗
}
