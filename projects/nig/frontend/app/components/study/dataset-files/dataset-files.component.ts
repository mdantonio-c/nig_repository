import {
  Component,
  Injector,
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
} from "@angular/core";
import { BasePaginationComponent } from "@rapydo/components/base.pagination.component";
import { DatasetFile } from "@app/types";
import {
  UploadxOptions,
  UploadState,
  UploadxService,
  Uploader,
} from "ngx-uploadx";
import { environment } from "@rapydo/../environments/environment";
import { Observable, Subject, of } from "rxjs";
import { takeUntil, take } from "rxjs/operators";

@Component({
  selector: "nig-dataset-files",
  templateUrl: "./dataset-files.component.html",
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DatasetFilesComponent extends BasePaginationComponent<DatasetFile> {
  @Input("dataset") uuid;
  @Input("readOnly") readonly;
  @Input() uploadCompleted;
  @Output() count: EventEmitter<number> = new EventEmitter<number>();

  uploadOptions: any = {};
  uploadProgress: any = {};
  uploads$: Observable<Uploader[]>;
  state$!: Observable<UploadState>;

  private unsubscribe$ = new Subject();

  constructor(
    protected injector: Injector,
    private uploadService: UploadxService,
    private cdr: ChangeDetectorRef
  ) {
    super(injector);
  }

  ngOnInit() {
    this.uploadOptions = {
      endpoint: `${environment.backendURI}/api/dataset/${this.uuid}/files/upload`,
      token: this.auth.getToken(),
      allowedTypes: "application/gzip",
      maxChunkSize: 16777216,
      // "application/x-zip-compressed,application/x-compressed,application/zip,multipart/x-zip",
      multiple: true,
      autoUpload: true,
    };
    this.uploads$ = this.uploadService.connect(this.uploadOptions);
    this.state$ = this.uploadService.events;

    this.state$.pipe(takeUntil(this.unsubscribe$)).subscribe((state) => {
      state.responseStatus == 200
        ? this.notify.showSuccess(
            `Upload completed: ${state.response.filename}`
          )
        : this.notify.showError(state.response);
    });

    this.init("File", `/api/dataset/${this.uuid}/files`, "DatasetFiles");
    this.set_resource_endpoint("/api/file");
    this.initPaging(20, false);
    const data$ = this.list();

    data$.subscribe({
      next: () => this.cdr.markForCheck(),
    });
  }

  onUpload(item: UploadState) {
    if (item.progress > 0) {
      this.uploadProgress[item.name] = item.progress;
    } else {
      // set 0 also in case of null and undefined
      delete this.uploadProgress[item.name];
    }

    if (
      item.progress == 100 &&
      item.remaining == 0 &&
      item.status == "complete"
    ) {
      const subject = this.list();
      subject.pipe(take(1)).subscribe((success: boolean) => {
        this.count.emit(this.data.length);
      });
      delete this.uploadProgress[item.name];
    }
  }

  protected delete_confirmation_callback(fileId: string) {
    this.notify.showSuccess(
      `Confirmation: ${this.resource_name} successfully deleted`
    );
    const subject = this.list();
    subject.pipe(take(1)).subscribe((success: boolean) => {
      this.count.emit(this.data.length);
    });
  }

  ngOnDestroy(): void {
    // @ts-ignore
    this.unsubscribe$.next();
    this.unsubscribe$.complete();
  }
}
