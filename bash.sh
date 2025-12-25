#！/bin/bash
# nohup bash bash.sh >> Bank_gpt-4o.log 2>&1 &
# python -m rca.run_agent_standard_multi_candidate --dataset Bank --controller_max_step 1 --start_idx 113  --end_idx 136


# nohup bash bash.sh >> Market_cloudbed-1_deepseek-r1-250528.log 2>&1 &
# python -m rca.run_agent_standard_multi_candidate --dataset Bank --controller_max_step 1 --start_idx 123  --end_idx 123
# python -m rca.run_agent_standard_multi_candidate --dataset Telecom --controller_max_step 1 --start_idx 1  --end_idx 1
python -m rca.run_agent_standard_multi_candidate --dataset Market/cloudbed-1 --controller_max_step 1 --start_idx 2  --end_idx 20

# nohup bash bash.sh >> Bank_cloudbed-1_deepseek-r1-250528.log 2>&1 &
# python -m rca.run_agent_standard_multi_candidate --dataset Bank --controller_max_step 1 --start_idx 2  --end_idx 2


# nohup bash bash.sh >> Bank_qwen3-235b-a22b-instruct-2507.log 2>&1 &
# python -m rca.run_agent_standard_multi_candidate --dataset Bank --controller_max_step 1 --start_idx 14  --end_idx 30

# nohup bash bash.sh >> Bank_llama3.1_8b-instruct-q8_0.log 2>&1 &
# python -m rca.run_agent_standard_multi_candidate --dataset Bank --start_idx 92 --end_idx 136