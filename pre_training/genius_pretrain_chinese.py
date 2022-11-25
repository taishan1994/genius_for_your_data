import numpy as np
import nltk
nltk.download('punkt')
from nltk.tokenize import sent_tokenize
import transformers
from transformers import BertTokenizer, AutoModel, AutoConfig, AutoModelForSeq2SeqLM
from transformers import Seq2SeqTrainingArguments, Seq2SeqTrainer, DataCollatorForSeq2Seq
from datasets import load_dataset, load_metric
from rouge import Rouge
import argparse
parser = argparse.ArgumentParser(allow_abbrev=False)
args = parser.parse_args()



# pretrained checkpoint:
model_checkpoint = '../model_hub/genius-base-chinese'
tokenizer = BertTokenizer.from_pretrained(model_checkpoint)


##################################################################
#                     data pre-processing
##################################################################

# load the preprocessed dataset with the four kinds of sketches
from datasets import load_from_disk
dataset_path = '../data/data_with_sketch'
dataset_name = dataset_path.split('/')[-1]
dataset_with_sketch = load_from_disk(dataset_path)
print(dataset_with_sketch)

# define the inputs and labels for sketch-based reconstruction pre-training
max_input_length = 50
max_target_length = 250

def preprocess_function(examples):
    """
    # inputs: the sketch
    # labels: the original text
    """
    model_inputs = tokenizer(examples['sketch'], max_length=max_input_length, truncation=True)
    with tokenizer.as_target_tokenizer():
        labels = tokenizer(examples['text'], max_length=max_target_length, truncation=True)
    model_inputs['labels'] = labels['input_ids']
    return model_inputs

import random
# 这里我们的数据有40133条，
N = 40133
tokenized_dataset = dataset_with_sketch.select(random.sample(range(40133),k=N)).map(preprocess_function, batched=True,
                                        remove_columns=dataset_with_sketch.column_names,
                                         batch_size=64,num_proc=8)


# ROUGE metric：
rouge_score = load_metric("rouge")
def compute_metrics(eval_pred):
    predictions, labels = eval_pred
    # Decode generated summaries into text
    decoded_preds = tokenizer.batch_decode(predictions, skip_special_tokens=True)
    # Replace -100 in the labels as we can't decode them
    labels = np.where(labels != -100, labels, tokenizer.pad_token_id)
    # Decode reference summaries into text
    decoded_labels = tokenizer.batch_decode(labels, skip_special_tokens=True)
    # ROUGE expects a newline after each sentence
    decoded_preds = ["\n".join(sent_tokenize(pred.strip())) for pred in decoded_preds]
    decoded_labels = ["\n".join(sent_tokenize(label.strip())) for label in decoded_labels]
    # Compute ROUGE scores
    result = rouge_score.compute(
        predictions=decoded_preds, references=decoded_labels, use_stemmer=True
    )
    # Extract the median scores
    result = {key: value.mid.fmeasure * 100 for key, value in result.items()}
    return {k: round(v, 4) for k, v in result.items()}


rouge = Rouge()

def get_avg(scores, rouge_name, metric_name):
    return sum([score[rouge_name][metric_name] for score in scores])

def compute_chinese_metrics(eval_pred):
    predictions, labels = eval_pred
    # Decode generated summaries into text
    decoded_preds = tokenizer.batch_decode(predictions, skip_special_tokens=True)
    # Replace -100 in the labels as we can't decode them
    labels = np.where(labels != -100, labels, tokenizer.pad_token_id)
    # Decode reference summaries into text
    decoded_labels = tokenizer.batch_decode(labels, skip_special_tokens=True)
    # ROUGE expects a newline after each sentence
    decoded_preds = ["\n".join(sent_tokenize(pred.strip())) for pred in decoded_preds]
    decoded_labels = ["\n".join(sent_tokenize(label.strip())) for label in decoded_labels]
    # Compute ROUGE scores
    scores = rouge.get_scores(decoded_preds, decoded_labels)
    avg_scores = {}
    length = len(scores)
    avg_p_1 = get_avg(scores, "rouge-1", "p") / length
    avg_r_1 = get_avg(scores, "rouge-1", "r") / length
    avg_f_1 = get_avg(scores, "rouge-1", "f") / length
    avg_p_2 = get_avg(scores, "rouge-2", "p") / length
    avg_r_2 = get_avg(scores, "rouge-2", "r") / length
    avg_f_2 = get_avg(scores, "rouge-2", "f") / length
    avg_p_l = get_avg(scores, "rouge-l", "p") / length
    avg_r_l = get_avg(scores, "rouge-l", "r") / length  
    avg_f_l = get_avg(scores, "rouge-l", "f") / length  
    """
    avg_scores = {
     "rouge-1":{
       "p": avg_p_1,
       "r": avg_r_1,
       "f": avg_f_1,
     },
     "rouge-2":{
       "p": avg_p_2,
       "r": avg_r_2,
       "f": avg_f_2,
     },
     "rouge-L":{
       "p": avg_p_l,
       "r": avg_r_l,
       "f": avg_f_l,
     },
    } 
    """
    # 只返回recall
    avg_scores = {
      "rouge-1": avg_r_1,
      "rouge-2": avg_r_2,
      "rouge-L": avg_r_l,
    }
    return avg_scores

##################################################################
#                     training
##################################################################

batch_size = 32
num_train_epochs = 3
model_name = model_checkpoint.split("/")[-1]

# load the pretrained weights
model = AutoModelForSeq2SeqLM.from_pretrained(model_checkpoint)


logging_steps = len(tokenized_dataset) // batch_size

output_dir = f"../saved_models/{model_name}-{dataset_name}-{N}"

training_args = Seq2SeqTrainingArguments(
    output_dir=output_dir,
    evaluation_strategy="steps",
    eval_steps = 500,
    save_strategy = 'epoch',
    save_total_limit = num_train_epochs,
    fp16 = True,
    learning_rate=5.6e-5,
    per_device_train_batch_size=batch_size,
    per_device_eval_batch_size=batch_size,
    weight_decay=0.01,
    num_train_epochs=num_train_epochs,
    predict_with_generate=True,
    logging_steps=logging_steps,
)

data_collator = DataCollatorForSeq2Seq(tokenizer, model=model)

val_dataset = tokenized_dataset.select(range(1000))

trainer = Seq2SeqTrainer(
    model,
    training_args,
    train_dataset=tokenized_dataset,
    eval_dataset=val_dataset, 
    data_collator=data_collator,
    tokenizer=tokenizer,
    compute_metrics=compute_metrics,
)


trainer.train(resume_from_checkpoint = False)
