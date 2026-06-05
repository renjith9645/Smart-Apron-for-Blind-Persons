#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>

// ================= WIFI =================
const char* ssid = "F.R.I.D.I";
const char* password = "12348765";

// ================= SERVER =================
ESP8266WebServer server(80);

// ================= PINS =================
const int gasPin  = A0;
const int ledPin  = D2;
const int btn1Pin = D5;
const int btn2Pin = D6;

// ================= SETTINGS =================
const int gasThreshold = 300;

// ================= VARIABLES =================
int gasValue = 0;

unsigned long btn1Count = 0;
unsigned long btn2Count = 0;

bool lastBtn1 = HIGH;
bool lastBtn2 = HIGH;

// ================= HTML PAGE =================
void handleRoot() {
  gasValue = analogRead(gasPin);

  String statusText  = (gasValue > gasThreshold) ? "⚠️ GAS DETECTED" : "SAFE";
  String statusColor = (gasValue > gasThreshold) ? "red" : "green";

  String html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="2">
<title>ESP8266 Gas Monitor</title>
<style>
body { font-family: Arial; text-align:center; margin-top:40px; }
.box { border:1px solid #ccc; padding:10px; margin:10px; display:inline-block; }
</style>
</head>
<body>

<h1>ESP8266 GAS MONITOR</h1>

<div class="box">
<h2>Gas Value</h2>
<h1>)rawliteral" + String(gasValue) + R"rawliteral(</h1>
<h2 style="color:)rawliteral" + statusColor + R"rawliteral(;">)rawliteral" + statusText + R"rawliteral(</h2>
</div>

<div class="box">
<h2>Button 1 Count</h2>
<h1>)rawliteral" + String(btn1Count) + R"rawliteral(</h1>
</div>

<div class="box">
<h2>Button 2 Count</h2>
<h1>)rawliteral" + String(btn2Count) + R"rawliteral(</h1>
</div>

</body>
</html>
)rawliteral";

  server.send(200, "text/html", html);
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);

  pinMode(ledPin, OUTPUT);
  pinMode(btn1Pin, INPUT_PULLUP);
  pinMode(btn2Pin, INPUT_PULLUP);

  Serial.print("[WIFI] Connecting");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("[WIFI] Connected");
  Serial.print("[WIFI] IP : ");
  Serial.println(WiFi.localIP());

  server.on("/", handleRoot);
  server.begin();
  Serial.println("[SERVER] Web server started");
}

// ================= LOOP =================
void loop() {
  server.handleClient();

  gasValue = analogRead(gasPin);

  // ---------- GAS + LED ----------
  if (gasValue > gasThreshold) {
    digitalWrite(ledPin, HIGH);
    Serial.println("[GAS] Value: " + String(gasValue) + " | ALERT");
  } else {
    digitalWrite(ledPin, LOW);
    Serial.println("[GAS] Value: " + String(gasValue) + " | SAFE");
  }

  // ---------- BUTTON 1 COUNT ----------
  bool btn1 = digitalRead(btn1Pin);
  if (btn1 == LOW && lastBtn1 == HIGH) {
    btn1Count++;
    Serial.println("[BTN1] Count: " + String(btn1Count));
    delay(250); // debounce
  }
  lastBtn1 = btn1;

  // ---------- BUTTON 2 COUNT ----------
  bool btn2 = digitalRead(btn2Pin);
  if (btn2 == LOW && lastBtn2 == HIGH) {
    btn2Count++;
    Serial.println("[BTN2] Count: " + String(btn2Count));
    delay(250); // debounce
  }
  lastBtn2 = btn2;

  delay(1000);
}
