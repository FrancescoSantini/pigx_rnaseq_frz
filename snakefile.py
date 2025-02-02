# PiGx RNAseq Pipeline.
#
# Copyright © 2017, 2018 Bora Uyar <bora.uyar@mdc-berlin.de>
# Copyright © 2017, 2018 Jonathan Ronen <yablee@gmail.com>
# Copyright © 2017-2024 Ricardo Wurmus <ricardo.wurmus@mdc-berlin.de>
#
# This file is part of the PiGx RNAseq Pipeline.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
Snakefile for pigx rnaseq pipeline
"""

import os
import yaml
import csv
import inspect

include: os.path.join(config['locations']['pkglibexecdir'], 'scripts/validate_input.py')
validate_config(config)

GENOME_FASTA = config['locations']['genome-fasta']
CDNA_FASTA = config['locations']['cdna-fasta']
READS_DIR = config['locations']['reads-dir']
OUTPUT_DIR = config['locations']['output-dir']
ORGANISM = config['organism']
MAPPER = config['mapping']['mapper']
GENOME_BUILD = config['mapping']['genome_build']

if os.getenv("PIGX_UNINSTALLED"):
    LOGO = os.path.join(config['locations']['pkgdatadir'], "images/Logo_PiGx.png")
else:
    LOGO = os.path.join(config['locations']['pkgdatadir'], "Logo_PiGx.png")

SCRIPTS_DIR = os.path.join(config['locations']['pkglibexecdir'], 'scripts/')

TRIMMED_READS_DIR = os.path.join(OUTPUT_DIR, 'trimmed_reads')
LOG_DIR           = os.path.join(OUTPUT_DIR, 'logs')
QC_DIR        = os.path.join(OUTPUT_DIR, 'QC')
MULTIQC_DIR       = os.path.join(OUTPUT_DIR, 'multiqc')
MAPPED_READS_DIR  = os.path.join(OUTPUT_DIR, 'mapped_reads')
BIGWIG_DIR      = os.path.join(OUTPUT_DIR, 'bigwig_files')
COUNTS_DIR  = os.path.join(OUTPUT_DIR, 'feature_counts')
SALMON_DIR        = os.path.join(OUTPUT_DIR, 'salmon_output')

def toolArgs(name):
    if 'args' in config['tools'][name]:
        return config['tools'][name]['args']
    else:
        return ""

def tool(name):
    cmd = config['tools'][name]['executable']
    return cmd + " " + toolArgs(name)

MULTIQC_EXEC = tool('multiqc')
STAR_EXEC_MAP    = tool('star_map')
STAR_EXEC_INDEX  = tool('star_index')
HISAT2_EXEC        = tool('hisat2')
HISAT2_BUILD_EXEC  = tool('hisat2-build')
SALMON_INDEX_EXEC  = tool('salmon_index')
SALMON_QUANT_EXEC  = tool('salmon_quant')
SAMTOOLS_EXEC    = tool('samtools')
GUNZIP_EXEC      = tool('gunzip') # for STAR
RSCRIPT_EXEC     = tool('Rscript')
SED_EXEC = tool('sed')
FASTP_EXEC = tool('fastp')
BAMCOVERAGE_EXEC = tool('bamCoverage')
MEGADEPTH_EXEC = tool('megadepth')

STAR_INDEX_THREADS   = config['execution']['rules']['star_index']['threads']
HISAT2_BUILD_THREADS = config['execution']['rules']['hisat2_index']['threads']
HISAT2_THREADS       = config['execution']['rules']['hisat2_map']['threads']
STAR_MAP_THREADS     = config['execution']['rules']['star_map']['threads']
SALMON_INDEX_THREADS = config['execution']['rules']['salmon_index']['threads']
SALMON_QUANT_THREADS = config['execution']['rules']['salmon_quant']['threads']

GTF_FILE = config['locations']['gtf-file']
SAMPLE_SHEET_FILE = config['locations']['sample-sheet']

DE_ANALYSIS_LIST = config.get('DEanalyses', {})

# Explicitly check if key 'covariates' is defined, set it to empty string otherwise.
for analysis in DE_ANALYSIS_LIST.keys():
    DE_ANALYSIS_LIST[analysis]['covariates'] = (
        DE_ANALYSIS_LIST[analysis]['covariates'] if 'covariates' in DE_ANALYSIS_LIST[analysis].keys()
        else ''
    )

## Load sample sheet
SAMPLE_SHEET = read_sample_sheet(SAMPLE_SHEET_FILE)

# Convenience function to access fields of sample sheet columns that
# match the predicate.  The predicate may be a string.
def lookup(column, predicate, fields=[]):
  if inspect.isfunction(predicate):
    records = [line for line in SAMPLE_SHEET if predicate(line[column])]
  else:
    records = [line for line in SAMPLE_SHEET if line[column]==predicate]
  return [record[field] for record in records for field in fields]

SAMPLES = [line['name'] for line in SAMPLE_SHEET]

## Conditional output files (some steps can be executed with multiple tools, the output file list
##  organised according to which tool the user wants to use)
BIGWIG_OUTPUT = []
if config['coverage']['tool'] == 'bamCoverage':
  fw = expand(os.path.join(BIGWIG_DIR, MAPPER, 'bamCoverage', '{sample}.forward.bw'), sample = SAMPLES)
  rv = expand(os.path.join(BIGWIG_DIR, MAPPER, 'bamCoverage', '{sample}.reverse.bw'), sample = SAMPLES) 
  both = expand(os.path.join(BIGWIG_DIR, MAPPER, 'bamCoverage', '{sample}.bw'), sample = SAMPLES)
  BIGWIG_OUTPUT = fw + rv + both
elif config['coverage']['tool'] == 'megadepth': 
  BIGWIG_OUTPUT = expand(os.path.join(BIGWIG_DIR, MAPPER, 'megadepth', '{sample}.all.bw'), sample = SAMPLES)
else:
  sys.exit("Error with the selected coverage computation method: Allowed options for coverage computation are 'megadepth' or 'bamCoverage'; check the settings file option under coverage->tool.")

COLLATED_DESEQ_MAPPER_OUTPUT = []
COLLATED_SALMON_TRANSCR_OUTPUT = []
COLLATED_SALMON_GENES_OUTPUT = []

if DE_ANALYSIS_LIST:
  repmap = expand(os.path.join(OUTPUT_DIR, "report", MAPPER, '{analysis}.deseq.report.html'), analysis = DE_ANALYSIS_LIST.keys())
  reptra = expand(os.path.join(OUTPUT_DIR, "report", 'salmon', '{analysis}.salmon.transcripts.deseq.report.html'), analysis = DE_ANALYSIS_LIST.keys())
  repgen = expand(os.path.join(OUTPUT_DIR, "report",  'salmon', '{analysis}.salmon.genes.deseq.report.html'), analysis = DE_ANALYSIS_LIST.keys())
  colmap = [os.path.join(OUTPUT_DIR, "report", MAPPER, "collated.deseq_results.tsv")]
  coltra = [os.path.join(OUTPUT_DIR, "report", 'salmon', "collated.transcripts.deseq_results.tsv")]
  colgen = [os.path.join(OUTPUT_DIR, "report", 'salmon', "collated.genes.deseq_results.tsv")]
  COLLATED_DESEQ_MAPPER_OUTPUT = repmap + colmap
  COLLATED_SALMON_TRANSCR_OUTPUT = reptra + coltra
  COLLATED_SALMON_GENES_OUTPUT = repgen + colgen
  
targets = {
    # rule to print all rule descriptions
    'help': {
        'description': "Print all rules and their descriptions.",
        'files': []
    },
    'final-report': {
        'description': "Produce a comprehensive report.  This is the default target.",
        'files':
        [os.path.join(OUTPUT_DIR, "input_annotation_stats.tsv"),
         os.path.join(MULTIQC_DIR, 'multiqc_report.html'),
         os.path.join(COUNTS_DIR, "raw_counts", "salmon", "counts_from_SALMON.transcripts.tsv"),
         os.path.join(COUNTS_DIR, "raw_counts", "salmon", "counts_from_SALMON.genes.tsv"),
         os.path.join(COUNTS_DIR, "normalized", "salmon", "TPM_counts_from_SALMON.transcripts.tsv"),
         os.path.join(COUNTS_DIR, "normalized", "salmon", "TPM_counts_from_SALMON.genes.tsv"),
         os.path.join(COUNTS_DIR, "raw_counts", MAPPER, "counts.tsv"),
         os.path.join(COUNTS_DIR, "normalized", MAPPER, "deseq_normalized_counts.tsv"),
         os.path.join(COUNTS_DIR, "normalized", MAPPER, "deseq_size_factors.txt")] +
        BIGWIG_OUTPUT +
        COLLATED_DESEQ_MAPPER_OUTPUT +
        COLLATED_SALMON_TRANSCR_OUTPUT +
        COLLATED_SALMON_GENES_OUTPUT
    },
    'deseq_report_star': {
        'description': "Produce one HTML report for each analysis based on STAR results.",
        'files':
         COLLATED_DESEQ_MAPPER_OUTPUT
    },
    'deseq_report_hisat2': {
        'description': "Produce one HTML report for each analysis based on Hisat2 results.",
        'files':
         COLLATED_DESEQ_MAPPER_OUTPUT
    },
    'deseq_report_salmon_transcripts': {
        'description': "Produce one HTML report for each analysis based on SALMON results at transcript level.",
        'files':
         COLLATED_SALMON_TRANSCR_OUTPUT
    },
    'deseq_report_salmon_genes': {
        'description': "Produce one HTML report for each analysis based on SALMON results at gene level.",
        'files':
         COLLATED_SALMON_GENES_OUTPUT
    },
    'star_map' : {
        'description': "Produce a STAR mapping results in BAM file format.",
        'files':
          expand(os.path.join(MAPPED_READS_DIR, "star", '{sample}_Aligned.sortedByCoord.out.bam'), sample = SAMPLES)
    },
    'star_counts': {
        'description': "Get count matrix from STAR mapping results using summarizeOverlaps.",
        'files':
          [os.path.join(COUNTS_DIR, "raw_counts", "star", "counts.tsv")]
    },
    'hisat2_map' : {
        'description': "Produce Hisat2 mapping results in BAM file format.",
        'files':
          expand(os.path.join(MAPPED_READS_DIR, "hisat2", '{sample}_Aligned.sortedByCoord.out.bam'), sample = SAMPLES)
    },
    'hisat2_counts': {
        'description': "Get count matrix from Hisat2 mapping results using summarizeOverlaps.",
        'files':
          [os.path.join(COUNTS_DIR, "raw_counts", "hisat2", "counts.tsv")]
    },
    'genome_coverage': {
        'description': "Compute genome coverage values from BAM files - save in bigwig format",
        'files':
          BIGWIG_OUTPUT
    },
    'salmon_index' : {
        'description': "Create SALMON index file.",
        'files':
          [os.path.join(OUTPUT_DIR, 'salmon_index', "pos.bin")]
    },
    'salmon_quant' : {
        'description': "Calculate read counts per transcript using SALMON.",
        'files':
          expand(os.path.join(SALMON_DIR, "{sample}", "quant.sf"), sample = SAMPLES) +
	  expand(os.path.join(SALMON_DIR, "{sample}", "quant.genes.sf"), sample = SAMPLES)
    },
    'salmon_counts': {
        'description': "Get count matrix from SALMON quant.",
        'files':
          [os.path.join(COUNTS_DIR, "raw_counts", "salmon", "counts_from_SALMON.transcripts.tsv"),
	   os.path.join(COUNTS_DIR, "raw_counts", "salmon", "counts_from_SALMON.genes.tsv"),
	   os.path.join(COUNTS_DIR, "normalized", "salmon", "TPM_counts_from_SALMON.transcripts.tsv"),
	   os.path.join(COUNTS_DIR, "normalized", "salmon", "TPM_counts_from_SALMON.genes.tsv")]
    },
    'multiqc': {
        'description': "Get multiQC report based on alignments and QC reports.",
        'files':
          [os.path.join(MULTIQC_DIR, 'multiqc_report.html')]
    }
}

# Selected output files from the above set.
selected_targets = config['execution']['target'] or ['final-report']

# FIXME: the list of files must be flattened twice(!).  We should make
# sure that the targets really just return simple lists.
from itertools import chain
OUTPUT_FILES = list(chain.from_iterable([targets[name]['files'] for name in selected_targets]))
# add annotation files for any target
OUTPUT_FILES.append(os.path.join(OUTPUT_DIR, "annotations.tgz"))

rule all:
  input:
    OUTPUT_FILES,

rule check_annotation_files:
  input: 
    dna = GENOME_FASTA,
    cdna = CDNA_FASTA,
    gtf = GTF_FILE
  output: 
    os.path.join(OUTPUT_DIR, 'input_annotation_stats.tsv')
  resources:
    mem_mb = lambda wc, input: max(1.5 * input.size_mb, config['execution']['rules']['check_annotation_files']['memory'])
  log: os.path.join(LOG_DIR, 'check_annotation_files.log')
  shell: "{RSCRIPT_EXEC} {SCRIPTS_DIR}/validate_input_annotation.R {input.gtf} {input.cdna} {input.dna} {OUTPUT_DIR} >> {log} 2>&1"

# save a copy of the annotation files in the results folder 
# for later backwards compatibility
rule record_annotation_files:
  input: 
    dna = GENOME_FASTA,
    cdna = CDNA_FASTA,
    gtf = GTF_FILE
  output:
    os.path.join(OUTPUT_DIR, "annotations.tgz")
  log: os.path.join(LOG_DIR, "record_annotation_files.log")
  shell: 
    """
    mkdir {OUTPUT_DIR}/annotations; cp {input.gtf} {input.cdna} {input.dna} {OUTPUT_DIR}/annotations 
    tar -czvf {output} {OUTPUT_DIR}/annotations --remove-files >> {log} 2>&1
    """

rule help:
  run:
    for key in sorted(targets.keys()):
      print('{}:\n  {}'.format(key, targets[key]['description']))

# Record any existing output files, so that we can detect if they have
# changed.
expected_files = {}
onstart:
    if OUTPUT_FILES:
        for name in OUTPUT_FILES:
            if os.path.exists(name):
                expected_files[name] = os.path.getmtime(name)

# Print generated target files.
onsuccess:
    if OUTPUT_FILES:
        # check if any existing files have been modified
        generated = []
        for name in OUTPUT_FILES:
            if name not in expected_files or os.path.getmtime(name) != expected_files[name]:
                generated.append(name)
        if generated:
            print("The following files have been generated:")
            for name in generated:
                print("  - {}".format(name))


rule translate_sample_sheet_for_report:
  input: SAMPLE_SHEET_FILE
  output: os.path.join(OUTPUT_DIR, "colData.tsv")
  shell: "{RSCRIPT_EXEC} {SCRIPTS_DIR}/translate_sample_sheet_for_report.R {input} > {output}"

# determine if the sample library is single end or paired end
def isSingleEnd(args):
  sample = args[0]
  files = lookup('name', sample, ['reads', 'reads2'])
  count = sum(1 for f in files if f)
  if count == 2:
      return False
  elif count == 1:
      return True

# function to pass read files to trim/filter/qc improvement
def trim_reads_input(args):
  sample = args[0]
  return [os.path.join(READS_DIR, f) for f in lookup('name', sample, ['reads', 'reads2']) if f]

# fastp both trims/filters reads and outputs QC reports in html/json format
rule trim_qc_reads_pe:
  input: trim_reads_input
  output:
    r1=os.path.join(TRIMMED_READS_DIR, "{sample}.trimmed.R1.fq.gz"),
    r2=os.path.join(TRIMMED_READS_DIR, "{sample}.trimmed.R2.fq.gz"),
    html=os.path.join(QC_DIR, "{sample}.pe.fastp.html"),
    json=os.path.join(QC_DIR, "{sample}.pe.fastp.json") #notice that multiqc recognizes files ending with fast.json
  group: "qc"
  resources:
    mem_mb = config['execution']['rules']['trim_qc_reads_pe']['memory']
  log: os.path.join(LOG_DIR, 'trim_reads.{sample}.log')
  shell: "{FASTP_EXEC} --in1 {input[0]} --in2 {input[1]} --out1 {output.r1} --out2 {output.r2} -h {output.html} -j {output.json} >> {log} 2>&1"

# fastp both trims/filters reads and outputs QC reports in html/json format
rule trim_qc_reads_se:
  input: trim_reads_input
  output:
    r = os.path.join(TRIMMED_READS_DIR, "{sample}.trimmed.fq.gz"),
    html=os.path.join(QC_DIR, "{sample}.se.fastp.html"),
    json=os.path.join(QC_DIR, "{sample}.se.fastp.json") #notice that multiqc recognizes files ending with fast.json
  group: "qc"
  resources:
    mem_mb = config['execution']['rules']['trim_qc_reads_se']['memory']
  log: os.path.join(LOG_DIR, 'trim_reads.{sample}.log')
  shell: "{FASTP_EXEC} --in1 {input[0]} --out1 {output.r} -h {output.html} -j {output.json} >> {log} 2>&1 "

rule star_index:
    input:
      gtf = GTF_FILE,
      genome = GENOME_FASTA,
      checked = rules.check_annotation_files.output
    output:
        star_index_file = os.path.join(OUTPUT_DIR, 'star_index', "SAindex")
    resources:
        mem_mb = config['execution']['rules']['star_index']['memory']
    params:
        star_index_dir = os.path.join(OUTPUT_DIR, 'star_index')
    log: os.path.join(LOG_DIR, 'star_index.log')
    shell: "{STAR_EXEC_INDEX} --runMode genomeGenerate --runThreadN {STAR_INDEX_THREADS} --genomeDir {params.star_index_dir} --genomeFastaFiles {input.genome} --sjdbGTFfile {input.gtf} >> {log} 2>&1"

rule hisat2_index:
    input: 
      GENOME_FASTA,
      rules.check_annotation_files.output
    output:
        [os.path.join(OUTPUT_DIR, "hisat2_index", f"{GENOME_BUILD}_index.{n}.ht2l") for n in [1, 2, 3, 4, 5, 6, 7, 8]]
    resources:
        mem_mb = config['execution']['rules']['hisat2_index']['memory']
    params:
        index_directory = os.path.join(OUTPUT_DIR, "hisat2_index"),
    log: os.path.join(LOG_DIR, 'hisat2_index.log')
    shell: "{HISAT2_BUILD_EXEC} -f -p {HISAT2_BUILD_THREADS} --large-index {input[0]} {params.index_directory}/{GENOME_BUILD}_index >> {log} 2>&1"

def map_input(args):
  sample = args[0]
  reads_files = [os.path.join(READS_DIR, f) for f in lookup('name', sample, ['reads', 'reads2']) if f]
  if len(reads_files) > 1:
    return [os.path.join(TRIMMED_READS_DIR, "{sample}.trimmed.R1.fq.gz".format(sample=sample)), os.path.join(TRIMMED_READS_DIR, "{sample}.trimmed.R2.fq.gz".format(sample=sample))]
  elif len(reads_files) == 1:
    return [os.path.join(TRIMMED_READS_DIR, "{sample}.trimmed.fq.gz".format(sample=sample))]

# I cannot do function composition, so it's gotta be this awkward definition instead.
def hisat2_file_arguments(args):
  files = map_input(args)
  if len(files) == 2:
    return "-1 {} -2 {}".format(files[0], files[1])
  elif len(files) == 1:
    return "-U {}".format(files[0])

rule star_map:
  input:
    # This rule really depends on the whole directory (see
    # params.index_dir), but we can't register it as an input/output
    # in its own right since Snakemake 5.
    index_file = rules.star_index.output.star_index_file,
    reads = map_input
  output:
    os.path.join(MAPPED_READS_DIR, 'star', '{sample}_Aligned.sortedByCoord.out.bam')
  resources:
    mem_mb = config['execution']['rules']['star_map']['memory']
  params:
    index_dir = rules.star_index.params.star_index_dir,
    output_prefix=os.path.join(MAPPED_READS_DIR, 'star', '{sample}_')
  log: os.path.join(LOG_DIR, 'star', 'star_map_{sample}.log')
  shell: "{STAR_EXEC_MAP} --runThreadN {STAR_MAP_THREADS} --genomeDir {params.index_dir} --readFilesIn {input.reads} --readFilesCommand '{GUNZIP_EXEC} -c' --outSAMtype BAM SortedByCoordinate --outFileNamePrefix {params.output_prefix} >> {log} 2>&1"

rule hisat2_map:
  input:
    index_files = rules.hisat2_index.output,
    reads = map_input
  output:
    os.path.join(MAPPED_READS_DIR, 'hisat2', '{sample}_Aligned.sortedByCoord.out.bam')
  resources:
    mem_mb = config['execution']['rules']['hisat2_map']['memory'],
    disk_mb=lambda wc, input: max(3 * input.size_mb, config['execution']['rules']['hisat2_map']['disk_mb'])
  params:
    samfile = lambda wildcards: os.path.join(MAPPED_READS_DIR, 'hisat2', "_".join([wildcards.sample, 'Aligned.out.sam'])),
    index_dir = rules.hisat2_index.params.index_directory,
    args = hisat2_file_arguments
  log:
    os.path.join(LOG_DIR, 'hisat2', 'hisat2_map_{sample}.log'),
    os.path.join(LOG_DIR, 'hisat2', 'samtools.hisat2.{sample}.log')
  shell:
    """
    {HISAT2_EXEC} -x {params.index_dir}/{GENOME_BUILD}_index -p {HISAT2_THREADS} -q -S {params.samfile} {params.args} >> {log[0]} 2>&1
    {SAMTOOLS_EXEC} view -bh {params.samfile} | {SAMTOOLS_EXEC} sort -o {output} >> {log[1]} 2>&1
    rm {params.samfile}
    """
    
rule index_bam:
  input: os.path.join(MAPPED_READS_DIR, MAPPER, '{sample}_Aligned.sortedByCoord.out.bam')
  output: os.path.join(MAPPED_READS_DIR, MAPPER, '{sample}_Aligned.sortedByCoord.out.bam.bai')
  resources:
    mem_mb = config['execution']['rules']['index_bam']['memory']
  log: os.path.join(LOG_DIR, 'samtools_index_{sample}.log')
  shell: "{SAMTOOLS_EXEC} index {input} {output} >> {log} 2>&1"

rule salmon_index:
  input:
      CDNA_FASTA,
      rules.check_annotation_files.output
  output:
      os.path.join(OUTPUT_DIR, 'salmon_index', "complete_ref_lens.bin"),
      os.path.join(OUTPUT_DIR, 'salmon_index', "ctable.bin"),
      os.path.join(OUTPUT_DIR, 'salmon_index', "ctg_offsets.bin"),
      os.path.join(OUTPUT_DIR, 'salmon_index', "duplicate_clusters.tsv"),
      os.path.join(OUTPUT_DIR, 'salmon_index', "info.json"),
      os.path.join(OUTPUT_DIR, 'salmon_index', "mphf.bin"),
      os.path.join(OUTPUT_DIR, 'salmon_index', "pos.bin"),
      os.path.join(OUTPUT_DIR, 'salmon_index', "rank.bin"),
      os.path.join(OUTPUT_DIR, 'salmon_index', "refAccumLengths.bin"),
      os.path.join(OUTPUT_DIR, 'salmon_index', "ref_indexing.log"),
      os.path.join(OUTPUT_DIR, 'salmon_index', "reflengths.bin"),
      os.path.join(OUTPUT_DIR, 'salmon_index', "refseq.bin"),
      os.path.join(OUTPUT_DIR, 'salmon_index', "seq.bin"),
      os.path.join(OUTPUT_DIR, 'salmon_index', "versionInfo.json")
  resources:
      mem_mb = config['execution']['rules']['salmon_index']['memory']
  params:
      salmon_index_dir = os.path.join(OUTPUT_DIR, 'salmon_index')
  log: os.path.join(LOG_DIR, "salmon", 'salmon_index.log')
  shell: "{SALMON_INDEX_EXEC} -t {input[0]} \
  -i {params.salmon_index_dir} \
  -p {SALMON_INDEX_THREADS} >> {log} 2>&1"

rule salmon_quant:
  input:
      gtf = GTF_FILE,
      index_files = rules.salmon_index.output,
      reads = map_input
  output:
      os.path.join(SALMON_DIR, "{sample}", "quant.sf"),
      os.path.join(SALMON_DIR, "{sample}", "quant.genes.sf"),
      os.path.join(SALMON_DIR, "{sample}", "libParams/flenDist.txt")
  resources:
      mem_mb = config['execution']['rules']['salmon_quant']['memory']
  params:
      salmon_index_dir = os.path.join(OUTPUT_DIR, 'salmon_index'),
      outfolder = os.path.join(SALMON_DIR, "{sample}")
  log: os.path.join(LOG_DIR, "salmon", 'salmon_quant_{sample}.log')
  run:
    if (len(input.reads) == 1):
        pe_se_args="-r {}".format(input.reads)
    else:
        pe_se_args="-1 {reads[0]} -2 {reads[1]}".format(reads=input.reads)
    COMMAND = f"\
{SALMON_QUANT_EXEC} -i {params.salmon_index_dir} -l A \
    -p {SALMON_QUANT_THREADS} {pe_se_args} \
    -o {params.outfolder} \
    --seqBias --gcBias \
    -g {input.gtf} >> {log} 2>&1"
    shell(COMMAND)

rule counts_from_SALMON:
  input:
      quantFiles = expand(os.path.join(SALMON_DIR, "{sample}", "quant.sf"), sample=SAMPLES),
      quantGenesFiles = expand(os.path.join(SALMON_DIR, "{sample}", "quant.genes.sf"), sample=SAMPLES),
      colDataFile = rules.translate_sample_sheet_for_report.output
  output:
      os.path.join(COUNTS_DIR, "raw_counts", "salmon", "counts_from_SALMON.transcripts.tsv"),
      os.path.join(COUNTS_DIR, "raw_counts", "salmon", "counts_from_SALMON.genes.tsv"),
      os.path.join(COUNTS_DIR, "normalized", "salmon", "TPM_counts_from_SALMON.transcripts.tsv"),
      os.path.join(COUNTS_DIR, "normalized", "salmon", "TPM_counts_from_SALMON.genes.tsv")
  resources:
      mem_mb = config['execution']['rules']['counts_from_SALMON']['memory']
  log: os.path.join(LOG_DIR, "salmon", 'salmon_import_counts.log')
  shell: "{RSCRIPT_EXEC} {SCRIPTS_DIR}/counts_matrix_from_SALMON.R {SALMON_DIR} {COUNTS_DIR} {input.colDataFile} >> {log} 2>&1"

# compute genome coverage using megadepth
rule coverage_megadepth:
  input:
    bam=os.path.join(MAPPED_READS_DIR, MAPPER, '{sample}_Aligned.sortedByCoord.out.bam'),
    bai=os.path.join(MAPPED_READS_DIR, MAPPER, '{sample}_Aligned.sortedByCoord.out.bam.bai')
  output:
    os.path.join(BIGWIG_DIR, MAPPER, 'megadepth', '{sample}.all.bw')
  params:
    out_prefix = os.path.join(BIGWIG_DIR, MAPPER, 'megadepth', '{sample}')
  log:
    os.path.join(LOG_DIR, MAPPER, 'coverage_megadepth.{sample}.log')
  resources:
    mem_mb = config['execution']['rules']['coverage_megadepth']['memory'],
    threads = config['execution']['rules']['coverage_megadepth']['threads']
  shell:
    """
    {MEGADEPTH_EXEC} {input.bam} --threads {resources.threads} --bigwig --prefix {params.out_prefix} >> {log} 2>&1
    """

# compute genome coverage using bamCoverage
rule coverage_bamCoverage:
  input:
    bam=os.path.join(MAPPED_READS_DIR, MAPPER, '{sample}_Aligned.sortedByCoord.out.bam'),
    bai=os.path.join(MAPPED_READS_DIR, MAPPER, '{sample}_Aligned.sortedByCoord.out.bam.bai')
  output:
    os.path.join(BIGWIG_DIR, MAPPER, 'bamCoverage', '{sample}.forward.bw'),
    os.path.join(BIGWIG_DIR, MAPPER, 'bamCoverage', '{sample}.reverse.bw'),
    os.path.join(BIGWIG_DIR, MAPPER, 'bamCoverage', '{sample}.bw')
  log:
    os.path.join(LOG_DIR, MAPPER, 'coverage_bamCoverage.forward.{sample}.log'),
    os.path.join(LOG_DIR, MAPPER, 'coverage_bamCoverage.reverse.{sample}.log'),
    os.path.join(LOG_DIR, MAPPER, 'coverage_bamCoverage.{sample}.log')
  resources:
    mem_mb = config['execution']['rules']['coverage_bamCoverage']['memory']
  shell:
    """
    {BAMCOVERAGE_EXEC} -b {input.bam} -o {output[0]} --filterRNAstrand forward >> {log[0]} 2>&1
    {BAMCOVERAGE_EXEC} -b {input.bam} -o {output[1]} --filterRNAstrand reverse >> {log[1]} 2>&1
    {BAMCOVERAGE_EXEC} -b {input.bam} -o {output[2]} >> {log[2]} 2>&1
    """

rule multiqc:
  input:
    salmon_output=expand(os.path.join(SALMON_DIR, "{sample}", "quant.sf"), sample = SAMPLES),
    salmon_flen=expand(os.path.join(SALMON_DIR, "{sample}", "libParams/flenDist.txt"), sample = SAMPLES),
    mapping_output=expand(os.path.join(MAPPED_READS_DIR, MAPPER, '{sample}_Aligned.sortedByCoord.out.bam'), sample=SAMPLES)
  group: "qc"
  output: os.path.join(MULTIQC_DIR, 'multiqc_report.html')
  resources:
    mem_mb = config['execution']['rules']['multiqc']['memory']
  log: os.path.join(LOG_DIR, f'multiqc.{MAPPER}.log')
  shell: "{MULTIQC_EXEC} -f -o {MULTIQC_DIR} {OUTPUT_DIR} >> {log} 2>&1"

rule count_reads:
  input:
    gtf = GTF_FILE,
    bam = os.path.join(MAPPED_READS_DIR, MAPPER, "{sample}_Aligned.sortedByCoord.out.bam"),
    bai = os.path.join(MAPPED_READS_DIR, MAPPER, "{sample}_Aligned.sortedByCoord.out.bam.bai")
  output:
    os.path.join(MAPPED_READS_DIR, MAPPER, "{sample}.read_counts.csv")
  resources:
    mem_mb = config['execution']['rules']['count_reads']['memory']
  log: os.path.join(LOG_DIR, MAPPER, "{sample}.count_reads.log")
  params:
    single_end = isSingleEnd,
    mode = config['counting']['counting_mode'],
    nonunique = config['counting']['drop_nonunique'],
    strandedness = config['counting']['strandedness'],
    feature = config['counting']['feature'],
    group_by = config['counting']['group_feature_by'],
    yield_size = config['counting']['yield_size']
  shell:
    "{RSCRIPT_EXEC} {SCRIPTS_DIR}/count_reads.R {wildcards.sample} {input.bam} {input.gtf} \
        {params.single_end} {params.mode} {params.nonunique} {params.strandedness} \
        {params.feature} {params.group_by} {params.yield_size} >> {log} 2>&1"

rule collate_read_counts:
  input:
    colDataFile = rules.translate_sample_sheet_for_report.output,
    count_files = expand(os.path.join(MAPPED_READS_DIR, MAPPER, "{sample}.read_counts.csv"), sample = SAMPLES)
  output:
    os.path.join(COUNTS_DIR, "raw_counts", MAPPER, "counts.tsv")
  resources:
    mem_mb = config['execution']['rules']['collate_read_counts']['memory']
  log: os.path.join(LOG_DIR, MAPPER, "collate_read_counts.log")
  params:
    mapped_dir = os.path.join(MAPPED_READS_DIR, MAPPER),
    script = os.path.join(SCRIPTS_DIR, "collate_read_counts.R")
  shell:
    "{RSCRIPT_EXEC} {params.script} {params.mapped_dir} {input.colDataFile} {output} >> {log} 2>&1"

# create a normalized counts table including all samples
# using the median-of-ratios normalization procedure ofcollate_deseq_results.R
# deseq2
rule norm_counts_deseq:
    input:
        counts_file = os.path.join(COUNTS_DIR, "raw_counts", MAPPER, "counts.tsv"),
        colDataFile = rules.translate_sample_sheet_for_report.output
    output:
        size_factors = os.path.join(COUNTS_DIR, "normalized", MAPPER, "deseq_size_factors.txt"),
        norm_counts = os.path.join(COUNTS_DIR, "normalized", MAPPER, "deseq_normalized_counts.tsv")
    resources:
      mem_mb = config['execution']['rules']['norm_counts_deseq']['memory']
    log:
        os.path.join(LOG_DIR, MAPPER, "norm_counts_deseq.log")
    params:
        script=os.path.join(SCRIPTS_DIR, "norm_counts_deseq.R"),
        outdir=os.path.join(COUNTS_DIR, "normalized", MAPPER)
    shell:
        "{RSCRIPT_EXEC} {params.script} {input.counts_file} {input.colDataFile} {params.outdir} >> {log} 2>&1"

rule report1:
  input:
    gtf=GTF_FILE,
    logo=LOGO,
    counts=os.path.join(COUNTS_DIR, "raw_counts", MAPPER, "counts.tsv"),
    coldata=str(rules.translate_sample_sheet_for_report.output),
  params:
    outdir=os.path.join(OUTPUT_DIR, "report", MAPPER),
    reportR=os.path.join(SCRIPTS_DIR, "runDeseqReport.R"),
    reportRmd=os.path.join(SCRIPTS_DIR, "deseqReport.Rmd"),
    description = lambda wildcards: DE_ANALYSIS_LIST[wildcards.analysis]['description'].replace("'",".").replace('"','.'),
    case = lambda wildcards: DE_ANALYSIS_LIST[wildcards.analysis]['case_sample_groups'],
    control = lambda wildcards: DE_ANALYSIS_LIST[wildcards.analysis]['control_sample_groups'],
    covariates = lambda wildcards: DE_ANALYSIS_LIST[wildcards.analysis]['covariates'],
    selfContained = lambda wildcards: DE_ANALYSIS_LIST[wildcards.analysis]['self_contained']
  log: os.path.join(LOG_DIR, MAPPER, "{analysis}.report.log")
  output:
    os.path.join(OUTPUT_DIR, "report", MAPPER, '{analysis}.deseq.report.html'),
    os.path.join(OUTPUT_DIR, "report", MAPPER, '{analysis}.deseq_results.tsv')
  resources:
    mem_mb = config['execution']['rules']['report1']['memory']
  shell:
    """{RSCRIPT_EXEC} $(readlink --canonicalize {params.reportR}) \
    --logo=$(readlink --canonicalize {input.logo})                \
    --prefix='{wildcards.analysis}'                               \
    --reportFile=$(readlink --canonicalize {params.reportRmd})    \
    --countDataFile=$(readlink --canonicalize {input.counts})     \
    --colDataFile=$(readlink --canonicalize {input.coldata})      \
    --gtfFile=$(readlink --canonicalize {input.gtf})              \
    --caseSampleGroups='{params.case}'                            \
    --controlSampleGroups='{params.control}'                      \
    --covariates='{params.covariates}'                            \
    --workdir=$(readlink --canonicalize {params.outdir})          \
    --organism='{ORGANISM}'                                       \
    --description='{params.description}'                          \
    --selfContained='{params.selfContained}' >> {log} 2>&1"""

rule deseq_collate_report1:
  input:
    html_reports=expand(os.path.join(OUTPUT_DIR, "report", MAPPER, '{analysis}.deseq.report.html'), analysis = DE_ANALYSIS_LIST.keys()),
    deseq_results=expand(os.path.join(OUTPUT_DIR, "report", MAPPER, '{analysis}.deseq_results.tsv'), analysis = DE_ANALYSIS_LIST.keys())
  params:
    mapper=MAPPER,
    outdir=os.path.join(OUTPUT_DIR, "report", MAPPER),
    inpdir=os.path.join(OUTPUT_DIR, "report", MAPPER),
    script=os.path.join(SCRIPTS_DIR, "collate_deseq_results.R"),
  log: os.path.join(LOG_DIR, MAPPER, "collate_deseq.report.log")
  output:
    os.path.join(OUTPUT_DIR, "report", MAPPER, 'collated.deseq_results.tsv')
  resources:
    mem_mb = config['execution']['rules']['deseq_collate_report1']['memory']
  shell:
    "{RSCRIPT_EXEC} {params.script} {params.mapper} {params.inpdir} {params.outdir} >> {log} 2>&1"

rule report2:
  input:
    gtf=GTF_FILE,
    logo=LOGO,
    counts=os.path.join(COUNTS_DIR, "raw_counts", "salmon", "counts_from_SALMON.transcripts.tsv"),
    coldata=str(rules.translate_sample_sheet_for_report.output)
  params:
    outdir=os.path.join(OUTPUT_DIR, "report", 'salmon'),
    reportR=os.path.join(SCRIPTS_DIR, "runDeseqReport.R"),
    reportRmd=os.path.join(SCRIPTS_DIR, "deseqReport.Rmd"),
    description = lambda wildcards: DE_ANALYSIS_LIST[wildcards.analysis]['description'].replace("'",".").replace('"','.'),
    case = lambda wildcards: DE_ANALYSIS_LIST[wildcards.analysis]['case_sample_groups'],
    control = lambda wildcards: DE_ANALYSIS_LIST[wildcards.analysis]['control_sample_groups'],
    covariates = lambda wildcards: DE_ANALYSIS_LIST[wildcards.analysis]['covariates'],
    selfContained = lambda wildcards: DE_ANALYSIS_LIST[wildcards.analysis]['self_contained']
  log: os.path.join(LOG_DIR, "salmon", "{analysis}.report.salmon.transcripts.log")
  output:
    os.path.join(OUTPUT_DIR, "report", 'salmon', '{analysis}.salmon.transcripts.deseq.report.html'),
    os.path.join(OUTPUT_DIR, "report", "salmon", '{analysis}.salmon.transcripts.deseq_results.tsv')
  resources:
    mem_mb = config['execution']['rules']['report2']['memory']
  shell:
    """{RSCRIPT_EXEC} $(readlink --canonicalize {params.reportR}) \
    --logo=$(readlink --canonicalize {input.logo})                \
    --prefix='{wildcards.analysis}.salmon.transcripts'            \
    --reportFile=$(readlink --canonicalize {params.reportRmd})    \
    --countDataFile=$(readlink --canonicalize {input.counts})     \
    --colDataFile=$(readlink --canonicalize {input.coldata})      \
    --gtfFile=$(readlink --canonicalize {input.gtf})              \
    --caseSampleGroups='{params.case}'                            \
    --controlSampleGroups='{params.control}'                      \
    --covariates='{params.covariates}'                            \
    --workdir=$(readlink --canonicalize {params.outdir})          \
    --organism='{ORGANISM}'                                       \
    --description='{params.description}'                          \
    --selfContained='{params.selfContained}' >> {log} 2>&1"""

rule deseq_collate_report2:
  input:
    html_reports=expand(os.path.join(OUTPUT_DIR, "report", "salmon", '{analysis}.salmon.transcripts.deseq.report.html'), analysis = DE_ANALYSIS_LIST.keys()),
    deseq_results=expand(os.path.join(OUTPUT_DIR, "report", "salmon", '{analysis}.salmon.transcripts.deseq_results.tsv'), analysis = DE_ANALYSIS_LIST.keys())
  params:
    mapper="transcripts",
    outdir=os.path.join(OUTPUT_DIR, "report", 'salmon'),
    inpdir=os.path.join(OUTPUT_DIR, "report", 'salmon'),
    script=os.path.join(SCRIPTS_DIR, "collate_deseq_results.R"),
  log: os.path.join(LOG_DIR, "salmon", "collate_transcripts_deseq.report.log")
  output:
    os.path.join(OUTPUT_DIR, "report", 'salmon', 'collated.transcripts.deseq_results.tsv')
  resources:
    mem_mb = config['execution']['rules']['deseq_collate_report2']['memory']
  shell:
    "{RSCRIPT_EXEC} {params.script} {params.mapper} {params.inpdir} {params.outdir} >> {log} 2>&1"

rule report3:
  input:
    gtf=GTF_FILE,
    logo=LOGO,
    counts=os.path.join(COUNTS_DIR, "raw_counts", "salmon", "counts_from_SALMON.genes.tsv"),
    coldata=str(rules.translate_sample_sheet_for_report.output)
  params:
    outdir=os.path.join(OUTPUT_DIR, "report", "salmon"),
    reportR=os.path.join(SCRIPTS_DIR, "runDeseqReport.R"),
    reportRmd=os.path.join(SCRIPTS_DIR, "deseqReport.Rmd"),
    description = lambda wildcards: DE_ANALYSIS_LIST[wildcards.analysis]['description'].replace("'",".").replace('"','.'),
    case = lambda wildcards: DE_ANALYSIS_LIST[wildcards.analysis]['case_sample_groups'],
    control = lambda wildcards: DE_ANALYSIS_LIST[wildcards.analysis]['control_sample_groups'],
    covariates = lambda wildcards: DE_ANALYSIS_LIST[wildcards.analysis]['covariates'],
    selfContained = lambda wildcards: DE_ANALYSIS_LIST[wildcards.analysis]['self_contained']
  log: os.path.join(LOG_DIR, "salmon", "{analysis}.report.salmon.genes.log")
  output:
    os.path.join(OUTPUT_DIR, "report", "salmon", '{analysis}.salmon.genes.deseq.report.html'),
    os.path.join(OUTPUT_DIR, "report", "salmon", '{analysis}.salmon.genes.deseq_results.tsv')
  resources:
    mem_mb = config['execution']['rules']['report3']['memory']
  shell:
    """{RSCRIPT_EXEC} $(readlink --canonicalize {params.reportR}) \
    --logo=$(readlink --canonicalize {input.logo})                \
    --prefix='{wildcards.analysis}.salmon.genes'                  \
    --reportFile=$(readlink --canonicalize {params.reportRmd})    \
    --countDataFile=$(readlink --canonicalize {input.counts})     \
    --colDataFile=$(readlink --canonicalize {input.coldata})      \
    --gtfFile=$(readlink --canonicalize {input.gtf})              \
    --caseSampleGroups='{params.case}'                            \
    --controlSampleGroups='{params.control}'                      \
    --covariates='{params.covariates}'                            \
    --workdir=$(readlink --canonicalize {params.outdir})          \
    --organism='{ORGANISM}'                                       \
    --description='{params.description}'                          \
    --selfContained='{params.selfContained}' >> {log} 2>&1"""

rule deseq_collate_report3:
  input:
    html_reports=expand(os.path.join(OUTPUT_DIR, "report", "salmon", '{analysis}.salmon.genes.deseq.report.html'), analysis = DE_ANALYSIS_LIST.keys()),
    deseq_results=expand(os.path.join(OUTPUT_DIR, "report", "salmon", '{analysis}.salmon.genes.deseq_results.tsv'), analysis = DE_ANALYSIS_LIST.keys())
  params:
    mapper="genes",
    outdir=os.path.join(OUTPUT_DIR, "report", 'salmon'),
    inpdir=os.path.join(OUTPUT_DIR, "report", 'salmon'),
    script=os.path.join(SCRIPTS_DIR, "collate_deseq_results.R"),
  log: os.path.join(LOG_DIR, "salmon", "collate_genes_deseq.report.log")
  output:
    os.path.join(OUTPUT_DIR, "report", 'salmon', 'collated.genes.deseq_results.tsv')
  resources:
    mem_mb = config['execution']['rules']['deseq_collate_report3']['memory']
  shell:
    "{RSCRIPT_EXEC} {params.script} {params.mapper} {params.inpdir} {params.outdir} >> {log} 2>&1"
