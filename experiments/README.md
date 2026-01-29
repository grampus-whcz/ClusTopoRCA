# get_result_from_tasks_info.py
extract from *_clean.md
```
2025-12-13 11:54:48.589 | INFO     | __main__:main:136 - Candidate 1: Passed Criteria: ['Redis02']
2025-12-13 11:54:48.589 | INFO     | __main__:main:137 - Candidate 1: Failed Criteria: ['high memory usage']
2025-12-13 11:54:48.590 | INFO     | __main__:main:138 - Candidate 1: Score: 0.5
2025-12-13 11:54:48.590 | INFO     | __main__:main:136 - Candidate 2: Passed Criteria: []
2025-12-13 11:54:48.590 | INFO     | __main__:main:137 - Candidate 2: Failed Criteria: ['Redis02', 'high memory usage']
2025-12-13 11:54:48.590 | INFO     | __main__:main:138 - Candidate 2: Score: 0.0
```
get *_extracted_tasks_info_1_135.md

# extract_key_info.py
get scores and tokens of some LLM

# log file naming rule
```
{dataset_name}_{task_name}_{model_name}.log
```
dataset_name: Bank, Market, and Telecom

task_name:
 - all_RAG, RAG k1
 - all_RAG_k2, RAG k2
 - all_RAG_k3, RAG k3
 - all_RAG_k4, RAG k4
 - all_RAG_k5, RAG k5
 - FusionTool_full, FusionTool full k4

model_name:
 - glm-4.5
 - glm-4.6
 - glm-4.7
 - deepseek-r1-250528
 - gemini-2.5-pro-preview-p
 - gpt-4o
 - llama3.1:8b-instruct-q8_0
 - qwen3-235b-a22b-instruct-2507

