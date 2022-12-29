FROM rapydo/backend-legacy39:2.4

ENV PYTHONDONTWRITEBYTECODE "true"

# RUN pip install --upgrade --no-cache-dir https://github.com/mdantonio/PyVCF/archive/master.zip

# to fix GLIBCXX_3.4.29 issue
RUN ln -sfn /usr/bin/python3.8 /usr/bin/python3
RUN apt-get update && apt-get install -y software-properties-common && add-apt-repository ppa:ubuntu-toolchain-r/test -y && apt-get update && apt-get upgrade -y libstdc++6
#RUN strings /lib/x86_64-linux-gnu/libstdc++.so.6 | grep GLIBCXX_3.4.29
RUN ln -sfn /usr/bin/python3.9 /usr/bin/python3

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

# Snakemake pinned to 6.4.0 due to
# https://github.com/snakemake/snakemake/issues/1166

# Note about samtools reinstall, due to the error:
# Samtools shared library libcrypto.so.1.0.0 not found
# => https://github.com/merenlab/anvio/issues/1479
# imagemagick is installed explicitely because is needed for the snakemake installation and without an explicit installation mamba could't find it
# Samtool is installed before snakemake otherwise it creates conflicts
RUN conda install --yes --freeze-installed python=3.9.0 && \
    conda update -n base -c defaults conda && \
    conda install --yes --freeze-installed -c conda-forge mamba stopit && \
    conda install --yes -c bioconda samtools=1.11 --force-reinstall && \
    mamba install -c conda-forge imagemagick=7.1 && \
    mamba install --yes --freeze-installed -c conda-forge -c bioconda snakemake==6.4.0 && \
    conda install --yes --freeze-installed -c bioconda gatk4==4.2.0 picard fastqc vcftools seqtk && \
    conda install --yes --freeze-installed -c daler sratoolkit && \
    conda install --yes --freeze-installed -c conda-forge yappi && \
    conda install --yes --freeze-installed pandas && \
    mamba install --yes --freeze-installed -c conda-forge -c bioconda bwa samblaster && \
    conda clean -afy

# needed by quality checks
RUN pip3 install --upgrade --no-cache-dir matplotlib
