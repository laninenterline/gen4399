/* gen4399 纯逻辑层（表单/载荷/判定），不依赖网络库。 */
#ifndef GEN4399_PAYLOAD_H
#define GEN4399_PAYLOAD_H

#include <stddef.h>

char *g4399_form_url(const char *app_id, int level);
char *g4399_parse_hidden(const char *html);
char *g4399_build_unified_payload(const char *hidden_pairs, const char *username,
                                  const char *password, const char *realname,
                                  const char *idcard, int send_realname,
                                  int *field_count, int *encrypted_count);
void g4399_classify(const char *path, int status, const char *body,
                    char *kind, size_t kind_len, char *message, size_t message_len);
void g4399_free(char *ptr);

#endif /* GEN4399_PAYLOAD_H */
