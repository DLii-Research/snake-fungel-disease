#!/bin/bash
#SBATCH --signal=INT@600

if [ -z "${deepdna_env_loaded}" ]; then
    echo "deepdna environment not loaded. Please run 'source env.sh' first."
    exit 1
fi

${command_prefix} ${python_tf} ./scripts/evaluation/setbert_evaluate_sfd_classifier.py \
    --pretrain-model-artifact $setbert_pretrain_sfd \
    --finetune-model-artifact $setbert_sfd_only_classifier_shallow \
    --sfd-dataset-path $datasets_path/SFD \
    --output-path $log_path/setbert-evaluate-sfd-only-classifier-shallow-64d-150l \
    $@
