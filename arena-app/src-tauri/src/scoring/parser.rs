use regex::Regex;

/// 从响应中提取 JSON 对象
pub fn extract_json_from_response(response_text: &str) -> Option<String> {
    lazy_static::lazy_static! {
        // 策略1: 尝试提取 Markdown 代码块中的 JSON
        static ref CODE_BLOCK_RE: Regex = Regex::new(r"```(?:json)?\s*(\{.*?\})\s*```").unwrap();
    }

    // 策略1: Markdown 代码块
    if let Some(captures) = CODE_BLOCK_RE.captures(response_text) {
        if let Some(json_str) = captures.get(1) {
            return Some(json_str.as_str().to_string());
        }
    }

    // 策略2: 找到所有完整的 JSON 对象，取最后一个（通常思维链在前，JSON在后）
    let json_objects = extract_all_json_objects(response_text);
    if !json_objects.is_empty() {
        // 优先返回包含 "scores" 字段的 JSON
        for obj in json_objects.iter().rev() {
            if obj.contains("\"scores\"") {
                return Some(obj.clone());
            }
        }
        // 否则返回最后一个有效 JSON
        return json_objects.last().cloned();
    }

    None
}

/// 从响应中提取 JSON 数组
pub fn extract_json_array_from_response(response_text: &str) -> Option<String> {
    lazy_static::lazy_static! {
        static ref CODE_BLOCK_RE: Regex = Regex::new(r"```(?:json)?\s*(\[.*?\])\s*```").unwrap();
    }

    // 策略1: Markdown 代码块
    if let Some(captures) = CODE_BLOCK_RE.captures(response_text) {
        if let Some(json_str) = captures.get(1) {
            let content = json_str.as_str().trim();
            if content.starts_with('[') && content.ends_with(']') {
                return Some(content.to_string());
            }
        }
    }

    // 策略2: 智能寻找最外层的 [] 对
    extract_outermost_json_array(response_text)
}

/// 提取所有 JSON 对象
/// 注意：此函数不处理字符串内的大括号，依赖 serde_json 验证来过滤无效 JSON
fn extract_all_json_objects(text: &str) -> Vec<String> {
    let mut objects = Vec::new();
    let mut depth = 0;
    let mut start_idx: Option<usize> = None;
    let mut in_string = false;
    let mut escape_next = false;

    for (i, char) in text.char_indices() {
        if escape_next {
            escape_next = false;
            continue;
        }

        match char {
            '\\' if in_string => {
                escape_next = true;
                continue;
            }
            '"' => {
                in_string = !in_string;
            }
            '{' if !in_string => {
                if depth == 0 {
                    start_idx = Some(i);
                }
                depth += 1;
            }
            '}' if !in_string => {
                // 忽略未匹配的右括号（depth 为 0 时）
                if depth == 0 {
                    continue;
                }
                depth -= 1;
                if depth == 0 {
                    if let Some(start) = start_idx {
                        let candidate = &text[start..=i];
                        // 验证是否是有效 JSON
                        if serde_json::from_str::<serde_json::Value>(candidate).is_ok() {
                            objects.push(candidate.to_string());
                        }
                        start_idx = None;
                    }
                }
            }
            _ => {}
        }
    }

    objects
}

/// 提取最外层的 JSON 数组
fn extract_outermost_json_array(text: &str) -> Option<String> {
    let mut candidates = Vec::new();

    // 寻找所有的 '[' 作为潜在起点
    let start_indices: Vec<usize> = text.match_indices('[').map(|(i, _)| i).collect();

    for start in start_indices {
        let mut depth = 0;
        let mut in_string = false;
        let mut escape = false;

        for (i, char) in text[start..].char_indices() {
            let actual_idx = start + i;

            if in_string {
                if escape {
                    escape = false;
                } else if char == '\\' {
                    escape = true;
                } else if char == '"' {
                    in_string = false;
                }
            } else {
                match char {
                    '"' => in_string = true,
                    '[' => depth += 1,
                    ']' => {
                        depth -= 1;
                        if depth == 0 {
                            let candidate = &text[start..=actual_idx];
                            if serde_json::from_str::<serde_json::Value>(candidate).is_ok() {
                                candidates.push(candidate.to_string());
                            }
                            break;
                        }
                    }
                    _ => {}
                }
            }
        }
    }

    // 返回最长的那个（通常是最外层的）
    candidates.into_iter().max_by_key(|s| s.len())
}

/// 从可能截断的文本中尽可能多地提取 JSON 对象
/// 用于批量评分响应的部分恢复
pub fn robust_parse_objects(text: &str) -> Vec<serde_json::Value> {
    let mut objects = Vec::new();

    // 查找所有 {"index": 模式的起始位置
    let start_indices: Vec<usize> = text.match_indices("{").map(|(i, _)| i).collect();

    for start in start_indices {
        // 检查是否以 {"index" 开头
        if !text[start..].starts_with("{\"") && !text[start..].starts_with("{ \"") {
            continue;
        }

        let mut depth = 0;
        let mut in_string = false;
        let mut escape = false;

        for (i, char) in text[start..].char_indices() {
            let actual_idx = start + i;

            if in_string {
                if escape {
                    escape = false;
                } else if char == '\\' {
                    escape = true;
                } else if char == '"' {
                    in_string = false;
                }
            } else {
                match char {
                    '"' => in_string = true,
                    '{' => depth += 1,
                    '}' => {
                        depth -= 1;
                        if depth == 0 {
                            let candidate = &text[start..=actual_idx];
                            if let Ok(obj) = serde_json::from_str::<serde_json::Value>(candidate) {
                                // 只保留包含 index 字段的对象
                                if obj.get("index").is_some() {
                                    objects.push(obj);
                                }
                            }
                            break;
                        }
                    }
                    _ => {}
                }
            }
        }
    }

    objects
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_json_from_code_block() {
        let response = r#"Some text
```json
{"scores": {"relevance": 4}, "analysis": "test"}
```
More text"#;

        let result = extract_json_from_response(response);
        assert!(result.is_some());
        let json = result.unwrap();
        assert!(json.contains("\"scores\""));
    }

    #[test]
    fn test_extract_json_from_plain_text() {
        let response = r#"Analysis here...
{"scores": {"relevance": 4}, "analysis": "test"}
More text"#;

        let result = extract_json_from_response(response);
        assert!(result.is_some());
    }

    #[test]
    fn test_extract_json_array_from_code_block() {
        let response = r#"```json
[{"index": 0, "scores": {}}, {"index": 1, "scores": {}}]
```"#;

        let result = extract_json_array_from_response(response);
        assert!(result.is_some());
    }

    #[test]
    fn test_robust_parse_objects() {
        // 模拟截断的响应
        let text = r#"[{"index": 0, "scores": {"relevance": 4}}, {"index": 1, "scores": {"relevance": 3"#;

        let objects = robust_parse_objects(text);
        assert_eq!(objects.len(), 1);
        assert_eq!(objects[0]["index"], 0);
    }

    #[test]
    fn test_extract_json_with_multiple_objects() {
        // 思维链在前，JSON 在后
        let response = r#"Let me think...
{"some": "intermediate"}
Final result:
{"scores": {"relevance": 5}, "analysis": "great"}"#;

        let result = extract_json_from_response(response);
        assert!(result.is_some());
        let json = result.unwrap();
        assert!(json.contains("\"relevance\": 5"));
    }
}
