FROM rapydo/backend:2.1

ENV PYTHONDONTWRITEBYTECODE "true"

RUN pip install --upgrade --no-cache-dir https://github.com/mdantonio/PyVCF/archive/master.zip

# Miniconda installation
RUN wget --quiet https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh \
    && mkdir /root/.conda \
    && bash Miniconda3-latest-Linux-x86_64.sh -b -p /opt/miniconda3 \
    && rm -f Miniconda3-latest-Linux-x86_64.sh \
    && chgrp -R developer /opt/miniconda3 \
    && chmod g+rx /opt/miniconda3/bin/*

ENV PATH=$PATH:/opt/miniconda3/bin
ENV PYTHONPATH=$PYTHONPATH:/opt/miniconda3/lib/python3.9/site-packages

# Mamba was installed with conda and is needed for SNAKEMAKE installation
# Installing snakemake directly with conda creates conflicts
# Last packages are installed with mamba because conda installation creates conflics for them

# Note about samtools reinstall, due to the error:
# Samtools shared library libcrypto.so.1.0.0 not found
# => https://github.com/merenlab/anvio/issues/1479
RUN conda install --yes --freeze-installed python=3.9.0 && \
    conda update -n base -c defaults conda && \
    conda install --yes --freeze-installed -c conda-forge mamba stopit && \
    mamba install --yes --freeze-installed -c conda-forge -c bioconda snakemake && \
    conda install --yes --freeze-installed -c bioconda gatk4==4.2.0 picard fastqc vcftools seqtk && \
    conda install --yes --freeze-installed -c daler sratoolkit && \
    conda install --yes --freeze-installed -c conda-forge yappi && \
    conda install --yes --freeze-installed pandas && \
    mamba install --yes --freeze-installed -c conda-forge -c bioconda bwa samblaster && \
    conda install -c bioconda samtools=1.11 --force-reinstall && \
    conda clean -afy
