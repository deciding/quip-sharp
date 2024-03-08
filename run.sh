BASE_MODEL=meta-llama/Llama-2-7b-hf

HESS=./hessians
HESS_PT=${HESS}/lm_test

CKPT=./ckpt
HF=./hf_quantized
CKPT_PT=$CKPT/lm_test_2
HF_PT=$HF/lm_test_2

LOG=./logs

#CUDA_VISIBLE_DEVICES=0,1,2,3 python -m quantize_llama.hessian_offline_llama --batch_size 2 --devset_size 6144 --ctx_size 4096 --base_model $BASE_MODEL --save_path $HESS_PT
CUDA_VISIBLE_DEVICES=0,1,2,3 python -m quantize_llama.quantize_finetune_llama --save_path $CKPT_PT --codebook E8P12  --scale_override 0.9 --base_model $BASE_MODEL  --hessian_path $HESS_PT --devset_size 384 --ft_valid_size 128 --ft_epochs 0
#CUDA_VISIBLE_DEVICES=0 python -m quantize_llama.hfize_llama --quantized_path $CKPT_PT --hf_output_path $HF_PT #>> $LOG/2_7b_2bit 2>&1 
#CUDA_VISIBLE_DEVICES=0,1,2,3 python -m quantize_llama.finetune_e2e_llama --base_model $BASE_MODEL --hf_path $HF_PT --devset_size 384 --ft_valid_size 128 --ft_epochs 0  --ft_bs 1 --ctx_size 4096 --ft_update_freq 2 --ft_train_mode --ckpt_path $CKPT_PT

#CUDA_VISIBLE_DEVICES=0 python -m eval.eval_ppl --hf_path $HF_PT #>> $LOG/2_7b_2bit 2>&1 

