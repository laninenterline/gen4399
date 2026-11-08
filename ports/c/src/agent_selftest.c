/* agent.c 的主机侧自测：用假 transport 模拟服务端，验证编排/判定/验证码重试。 */
#include "agent.h"
#include "gen4399.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int call_count = 0;
static int captcha_asked = 0;

static char *fake_transport(void *ctx, const char *url, const char *method,
                            const char *content_type, const char *body, const char *cookie)
{
    (void)ctx; (void)method; (void)content_type; (void)cookie;
    call_count++;
    const char *response;
    if (strstr(url, "regFrame.do")) {
        /* 1) 拉注册表单 */
        response = "<form action=\"/ptlogin/register.do\"><input type=\"hidden\" name=\"appId\" value=\"u4399\">"
                   "<input type=\"hidden\" name=\"sec\" value=\"1\">"
                   "<input type=\"hidden\" name=\"mainDivId\" value=\"popup_reg_div\">"
                   "<input type=\"hidden\" name=\"fCaptcha\" value=\"\"></form>";
    } else if (strstr(url, "captcha.do")) {
        response = "IMAGEDATA";
    } else if (strstr(url, "register.do") && strstr(body, "inputCaptcha")) {
        response = "var x;isAutoRegSuccess = true;";
    } else if (strstr(url, "register.do")) {
        /* 第一次 POST 要求验证码 */
        response = "<img id='captcha' src=\"/ptlogin/captcha.do?captchaId=abc123\"/>"
                   "<input id='inputCaptcha' name='inputCaptcha'/>";
    } else {
        response = "";
    }
    size_t len = strlen("200||") + strlen(response) + 1;
    char *out = malloc(len);
    snprintf(out, len, "200||%s", response);
    return out;
}

static void fake_progress(void *ctx, int index, int total, const char *username,
                          const char *password, const char *kind, int ok, const char *message)
{
    (void)ctx; (void)password;
    printf("progress: [%d/%d] %s -> %s (ok=%d) %s\n", index, total, username, kind, ok, message);
}

static char *fake_captcha(void *ctx, const unsigned char *image, int length)
{
    (void)ctx; (void)image;
    captcha_asked++;
    printf("captcha: %d 字节图片，回答 ABCD\n", length);
    return strdup("ABCD");
}

int main(void)
{
    g4399_agent_hooks hooks = {NULL, fake_transport, fake_progress, fake_captcha, NULL};
    g4399_agent_config config = {"unified", 1, "", "", 0, 0, 1, "u4399", 4};

    int success = g4399_agent_run("王五|110105198803121893\n", &config, &hooks);
    printf("结果：成功 %d，请求 %d 次，验证码 %d 次\n", success, call_count, captcha_asked);

    int failures = 0;
    if (success != 1) { printf("[FAIL] 应当成功 1 个\n"); failures++; }
    else printf("[OK] 编排跑通并判定 success\n");
    if (captcha_asked != 1) { printf("[FAIL] 应当问 1 次验证码\n"); failures++; }
    else printf("[OK] 验证码重试生效\n");

    /* dry-run 不应发 POST */
    call_count = 0;
    captcha_asked = 0;
    g4399_agent_config dry = {"unified", 1, "", "", 0, 1, 1, "u4399", 4};
    g4399_agent_run("王五|110105198803121893\n", &dry, &hooks);
    if (call_count == 1) printf("[OK] dry-run 只发了一次 GET\n");
    else { printf("[FAIL] dry-run 请求数异常：%d\n", call_count); failures++; }

    printf("%s\n", failures ? "自测失败" : "自测通过");
    return failures ? 1 : 0;
}
