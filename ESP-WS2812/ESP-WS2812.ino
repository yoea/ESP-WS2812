/*
 * WeMOS D1 mini 60 颗音乐电平灯带 - 固件端（哑终端），固件版本 v6
 *
 * 从 ESP-01S-LightStrip-60/ESP-01S-LightStrip-60.ino（v6）原样移植，
 * 只改「跑在哪块板子上」相关的东西，协议、灯效策略、保护机制全部一致。
 *
 * 与 ESP-01S 版的差异（仅硬件相关）：
 *   - 板子：WeMOS D1 mini（ESP8266EX，4MB flash），不再是 ESP-01S 1MB 小座子
 *   - 信号脚 GPIO0 -> GPIO4，即板子丝印 D2：
 *       * GPIO0 是 strapping 引脚，上电被拉低就会进下载模式，挂长线还容易被干扰，
 *         所以 D1 mini 上把数据线接到 D2（GPIO4）这个普通 IO。
 *       * 60 颗 WS2812 数据线接 D2，GND 与灯带共地，5V 从 D1 mini 的 5V/VIN 取。
 *   - 板载 LED 仍是 GPIO2（丝印 D4），低电平点亮，可以正常控制：
 *       常驻灯态 0x07、事件脉冲 0x08、主机失联 PWM 呼吸都保留，
 *       与数据脚 GPIO4 完全独立，互不干扰。
 *   - 设备身份证的型号字符串改成 "D1MINI-LED60"（12 字节，与 ESP-01S 的
 *     "ESP01S-LED60" 等长），电脑端靠它区分「这次接的是哪块板」。
 *     芯片唯一序列号（ESP.getChipId()）不变，仍由固件自报，烧录时不用手填。
 *
 * 电脑端发 60 组 RGB（180B），**每颗灯珠单独一个颜色**；帧长 185B @50Hz
 *   = 92.5kbit/s，占 115200 的 80.3%（100Hz 会超带宽，所以必须 50Hz）
 * 全局亮度硬限 128/255 = 50%，防止 60 颗灯带过流
 * FIRMWARE_VERSION 6，握手时上报 + 17B 身份帧，避免旧固件 / 别的设备误配
 *
 * 帧格式： A5 5A | CMD | LEN | PAYLOAD[LEN] | CRC8
 *   CRC8 覆盖 CMD + LEN + PAYLOAD，多项式 0x07，初值 0x00
 *
 * 命令：
 *   0x01 SET_ALL      payload 180B，RGB 顺序，第 i 颗 = payload[i*3 .. i*3+2]
 *   0x03 BRIGHTNESS   payload 1B，全局亮度 0-255（固件 clamp 到 128）
 *   0x04 HEARTBEAT    payload 0B
 *   0x06 OFF          payload 0B，立即熄灭
 *   0x07 STATUS_LED   payload 1B，板载 LED 常驻灯态：0=灭 1=常亮 2=慢闪
 *   0x08 STATUS_PULSE payload 1B，板载 LED 短闪几下后自动熄灭（事件提示）
 *   0x10 HANDSHAKE    payload 0B，回应 17B 身份帧：
 *                     [0]=版本 [1..12]="D1MINI-LED60" [13..16]=芯片ID(小端)
 *
 * 板载 LED（GPIO2 / D4，低电平点亮）—— 只在「有事发生」时出声。
 * 「在放歌」这件事 60 颗灯珠已经说得很清楚了，这颗灯再复述一遍纯属打扰，
 * 所以主机端平时根本不点它，只在事件瞬间发一条脉冲：
 *   切歌      闪 2 下（0x08 payload=2）
 *   状态切换  闪 3 下（0x08 payload=3）
 * 脉冲结束自动回到熄灭，其余时间全灭。
 *
 * 主机失联时灯带自己收尾（fail-safe）：
 *   超过 HEARTBEAT_TIMEOUT(3s) 没收到任何帧，且主机最后一条不是 OFF
 *   -> 1 秒内从尾颗往头逐颗灭掉（WIPE_OFF_MS/60 = 16ms 一颗），
 *     观感和网页上点「灭」开关完全一样。灭完板载 LED 转 PWM 呼吸报警。
 *   主机主动退出会先发 OFF，这时保持熄灭 —— 手动关掉不误报。
 *   上电后主机一直没连上，同样会进入呼吸，表示「固件在跑但没人在推数据」。
 *   进入呼吸前会等逐颗熄灯走完：PWM 一开就不能再 show()，顺序不能反。
 * 灯带本身是 fail-safe 全灭：pixels 上电先 clear，CMD_BRIGHTNESS 也先 clear，
 *   任何「只恢复亮度」的帧都不会把关机前的旧颜色点亮。开机 / 待机 / 唤醒
 *   没人推 SET_ALL 时灯带一律是黑的，不依赖 Windows 在关机瞬间发 OFF。
 *
 * 为什么这里敢用 analogWrite：ESP8266 的 PWM 靠定时器中断实现，会打断 WS2812 的
 * 软件位翻转 —— 但呼吸只在「主机已经不发数据」的窗口里启用，这段时间一次
 * strip.show() 都不会调用，没有位翻转，也就没有可被打断的时序。
 * 收到任何一帧立刻退出 PWM、恢复成纯 digitalWrite。
 * （GPIO2 同时是 strapping 引脚，低电平点亮 + 外部上拉：上电是高=灭，不干扰启动。）
 *
 * 保护机制：
 *   - 帧解析带超时重置，一串干扰字节不会把状态机卡死
 *   - 心跳超时(3s)后 1 秒内逐颗灭掉：电脑关机/休眠/进程退出时不会僵在最后一帧
 */

#include <Adafruit_NeoPixel.h>
#include <ESP8266WiFi.h>

// D1 mini 丝印 D2 = GPIO4：普通 IO，不参与 strapping，也不会被串口占用。
// 别改回 GPIO0 —— 那是下载模式引脚，上电被拉低就起不来。
#define LED_PIN    4          // D2 / GPIO4，接灯带 DIN
#define LED_COUNT  60         // 物理灯珠数 = 电脑端发来的颜色数（逐颗独立控色）
#define BAUD_RATE  115200     // 185B/帧 @50Hz = 92.5kbit/s，占 115200 的 80.3%

#define HDR0              0xA5
#define HDR1              0x5A
#define MAX_PAYLOAD       192  // 60 颗 x 3B = 180B，留 12B 余量
#define FRAME_TIMEOUT_MS  100
#define HEARTBEAT_TIMEOUT 3000
// 失联熄灯：跟网页上那个「灭」开关一模一样 —— 一秒内从尾颗开始逐颗灭掉。
// 60 颗 / 1000ms = 16.6ms 一颗，取整 16ms（60 x 16 = 960ms）。
#define WIPE_OFF_MS       1000
#define WIPE_OFF_STEP_MS  (WIPE_OFF_MS / LED_COUNT)

#define CMD_SET_ALL    0x01
#define CMD_BRIGHTNESS 0x03
#define CMD_HEARTBEAT  0x04
#define CMD_OFF        0x06
#define CMD_STATUS_LED 0x07
#define CMD_STATUS_PULSE 0x08
#define CMD_HANDSHAKE  0x10

#define FIRMWARE_VERSION 6
// 设备身份证：型号字符串 + ESP8266 芯片唯一 ID。主机靠它认灯带，不靠 COM 号。
// "D1MINI-LED60" = 12 字节，与 ESP-01S 版的 "ESP01S-LED60" 等长，
// 所以 IDENTITY_LEN 仍是 17，电脑端解析代码一行都不用改结构。
#define DEVICE_MODEL     "D1MINI-LED60"   // 12 字节，不含结尾 '\0'
#define DEVICE_MODEL_LEN 12
#define IDENTITY_LEN     17               // 1B 版本 + 12B 型号 + 4B 芯片ID
#define BRIGHTNESS_CAP   128  // 硬限 50%：60 颗灯带不许超过这个全局亮度

// ---- 板载 LED（D1 mini 板载蓝灯，丝印 D4 = GPIO2，低电平点亮）----
#define STATUS_LED_PIN   2      // GPIO2 / D4 板载蓝灯，与数据脚 GPIO4 独立
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

// ---- 亮度与失联熄灯 ----
uint8_t targetBrightness = 128;
uint8_t currentLevel = 128;
bool    fading = false;         // 主机失联，正在逐颗熄灯
uint32_t fadeStartMs = 0;       // 逐颗熄灯的起点
uint16_t fadeLit = 0;           // 当前还亮着的颗数（从 LED_COUNT 倒数到 0）

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
    // 灯带还在逐颗灭就先不接管：灭的过程里有 show()，PWM 一开就会打断 WS2812 时序。
    // 等它灭完再呼吸，视觉上也正好是「灯光逐颗熄掉 → 板载灯接手」的接力。
    if (fading && fadeLit > 0) {
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
      // 60 颗逐颗独立控色，第 i 颗直接用 payload[i*3 .. i*3+2]。
      // 相邻灯珠可以完全不同色，不做任何「每组复制到相邻几颗」。
      // 60 颗 show() 约 1.8ms 关中断，115200 下只落 ~21 字节进 UART FIFO，安全。
      for (uint8_t i = 0; i < LED_COUNT; i++) {
        strip.setPixelColor(i, strip.Color(payload[i * 3],
                                           payload[i * 3 + 1],
                                           payload[i * 3 + 2]));
      }
      // 收到有效数据就从熄灯状态唤醒（上面已经把 60 颗像素全部重设过了）
      if (fading) {
        fading = false;
        fadeLit = LED_COUNT;      // 复位成「全亮」，下次失联重新从尾颗灭起
        currentLevel = targetBrightness;
        strip.setBrightness(currentLevel);
      }
      hostSaidOff = false;         // 主机在正常推流，撤销「主动熄灯」标记
      strip.show();
      break;
    }

    case CMD_BRIGHTNESS: {
      if (len < 1) return;
      // 硬限 50%：电脑端发 255 也只到 128，防止 60 颗灯带过流。
      // 只 clamp 这一处，不再叠加别的折扣，避免两道相乘把亮度压没。
      // ★ 亮度帧绝不能点亮旧数据：关机 / 待机时 USB 还有电、固件不重启，
      //   pixels 里可能还留着上一帧颜色（失联熄灯现在会把它们逐颗清成 0，
      //   但主机被强杀、来不及走完 1 秒时仍可能剩下前几颗）。
      //   以前这里直接 setBrightness + show()，开机第一条 CMD_BRIGHTNESS
      //   就把关机前那颗灯原样复活了（「开机后中间莫名其妙亮一颗」的真凶）。
      //   先 clear 再 show：真正的颜色一律由紧随其后的 CMD_SET_ALL 给。
      targetBrightness = min(payload[0], (uint8_t)BRIGHTNESS_CAP);
      currentLevel = targetBrightness;
      fading = false;
      strip.clear();
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
      fadeLit = 0;
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
      // 每次握手都自报身份：版本 + 型号 + 芯片唯一序列号。
      // 主机换了 USB 口 / 同时插着多个 CH340 时，靠这 17B 认出本灯带；
      // 型号 D1MINI-LED60 还能区分「这是 D1 mini 的 60 颗，不是 ESP-01S 的」。
      uint8_t id[IDENTITY_LEN];
      memset(id, 0, sizeof(id));
      id[0] = FIRMWARE_VERSION;
      memcpy(id + 1, DEVICE_MODEL, DEVICE_MODEL_LEN);
      uint32_t chip = ESP.getChipId();       // 每片 ESP8266 唯一，不用烧录时手填
      id[13] = (uint8_t)(chip & 0xFF);
      id[14] = (uint8_t)((chip >> 8) & 0xFF);
      id[15] = (uint8_t)((chip >> 16) & 0xFF);
      id[16] = (uint8_t)((chip >> 24) & 0xFF);
      sendFrame(CMD_HANDSHAKE, id, IDENTITY_LEN);
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
  // begin() 里 malloc 出来的 pixels 缓冲区不保证清零，第一次 show() 之前
  // 必须先 clear()，否则上电瞬间会闪一下随机颜色的灯珠。
  strip.clear();
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

  // 3) 心跳超时：电脑关机 / 休眠 / 进程退出时，1 秒内从尾颗开始逐颗灭掉，
  //    跟网页上点「灭」开关完全同一个观感（尾 → 头，960ms 走完）。
  if (!fading && (millis() - lastFrameMs) > HEARTBEAT_TIMEOUT) {
    fading = true;
    fadeStartMs = millis();
    fadeLit = LED_COUNT;
  }
  if (fading) {
    // 按经过的时间反推「该剩几颗」，而不是每轮递减一次：主循环偶尔被串口处理
    // 拖慢时，下一次会自动补上漏掉的颗数，1 秒总时长不会被拉长。
    uint32_t gone = (millis() - fadeStartMs) / WIPE_OFF_STEP_MS;
    uint16_t lit = (gone >= LED_COUNT) ? 0 : (uint16_t)(LED_COUNT - gone);
    if (lit < fadeLit) {
      for (uint16_t i = lit; i < fadeLit; i++) strip.setPixelColor(i, 0, 0, 0);
      fadeLit = lit;
      strip.show();
    }
  }

  // 4) 板载 LED：正常态由主机指定，主机失联转 4Hz 报警
  updateStatusLed();

  yield();   // 喂看门狗
}
