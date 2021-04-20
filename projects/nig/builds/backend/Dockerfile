FROM rapydo/backend:1.1

ENV PYTHONDONTWRITEBYTECODE "true"

RUN pip install --upgrade --no-cache-dir https://github.com/mdantonio/PyVCF/archive/master.zip

# Miniconda installation
RUN wget --quiet https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh \
    && mkdir /root/.conda \
    && bash Miniconda3-latest-Linux-x86_64.sh -b \
    && rm -f Miniconda3-latest-Linux-x86_64.sh

ENV PATH=$PATH:/root/miniconda3/bin

# Mamba was installed with conda and is needed for SNAKEMAKE installation
# Installing snakemake directly with conda creates conflicts
# Last packages are installed with mamba because conda installation creates conflics for them

RUN conda update -n base -c defaults conda && \
    conda install --yes --freeze-installed -c conda-forge mamba && \
    mamba install --yes --freeze-installed -c conda-forge -c bioconda snakemake && \
    conda install --yes --freeze-installed -c bioconda gatk4==4.2.0 picard fastqc vcftools seqtk && \
    conda install --yes --freeze-installed -c daler sratoolkit && \
    conda install --yes --freeze-installed -c conda-forge yappi && \
    conda install --yes --freeze-installed pandas && \
    mamba install --yes --freeze-installed -c conda-forge -c bioconda bwa samblaster samtools && \
    conda clean -afy
